"""AI Maturity Engine: evidence-based readiness assessment, per broker.

Reads Memory A (historical backtests), Memory B (walk-forward / out-of-sample) and
Memory C (live virtual) from the MemoryStore and grades the evidence against
configurable thresholds. Readiness is reported as SEPARATE stages:

  observation_ready       -> the system can observe the market (read-only)
  data_sufficient         -> enough trades / days / regimes exist to judge anything
  statistically_validated -> the evidence clears the performance + calibration gates
  operationally_ready     -> infrastructure checks pass and no emergency stop is active
  live_authorized         -> ALWAYS False here. Only the owner grant in security.auth can
                             authorize real execution; this module only *reads* its status.

THE MATURITY SCORE NEVER ENABLES TRADING. It is a progress indicator for humans.
A strategy validated on one broker is NOT validated on another: every assessment is
scoped to exactly one broker's trades.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from ..domain import MemoryDomain, SimTrade, utcnow
from ..engines.metrics import compute_metrics
from ..memory.store import MemoryStore

SCORE_DISCLAIMER = ("The maturity score is informational only and NEVER enables trading. Real execution "
                    "requires the owner's explicit, time-limited authorization grant.")


@dataclass
class MaturityThresholds:
    # data sufficiency
    min_historical_trades: int = 300
    min_oos_trades: int = 100
    min_virtual_trades: int = 100
    min_virtual_days: float = 30.0
    min_regime_coverage: int = 3          # regimes with >= min_trades_per_regime OOS+virtual trades
    min_trades_per_regime: int = 20
    # statistical validation
    min_profit_factor: float = 1.2        # applied to OOS and virtual separately
    max_drawdown_pct: float = 10.0        # applied to OOS and virtual separately
    min_expectancy: float = 0.0           # money per trade, OOS and virtual separately
    require_positive_expectancy_ci: bool = True   # 95% lower bound of combined expectancy > 0
    max_calibration_error: float = 0.10   # expected calibration error on virtual trades
    min_calibration_trades: int = 50
    max_oos_degradation: float = 0.5      # OOS expectancy must retain >= 50% of historical (if positive)
    # operational
    max_tick_age_seconds: float = 60.0
    starting_equity: float = 10_000.0


@dataclass
class GateResult:
    name: str
    group: str                 # data | statistical | operational
    passed: bool
    observed: float | str | None
    threshold: float | str | None
    comparison: str            # ">=", "<=", ">", "=="
    progress: float            # 0..1 toward the threshold (for the score)
    detail: str = ""


@dataclass
class MaturityReport:
    broker: str
    strategy_version: str | None
    time: datetime
    score: float
    gates: list[GateResult]
    failed_gates: list[str]
    required_tests: list[str]
    uncertainty: dict
    counts: dict
    observation_ready: bool
    data_sufficient: bool
    statistically_validated: bool
    operationally_ready: bool
    live_authorized: bool                  # always False from this module
    owner_grant_status: dict
    disclaimer: str = SCORE_DISCLAIMER
    scope_note: str = "Validation is broker-specific: evidence from other brokers is not counted."

    def to_dict(self) -> dict:
        d = asdict(self)
        d["time"] = self.time.isoformat()
        return d


# -- statistics helpers --------------------------------------------------------
def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mean_and_se(values: list[float]) -> tuple[float, float | None]:
    n = len(values)
    if n == 0:
        return 0.0, None
    m = sum(values) / n
    if n < 2:
        return m, None
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))
    return m, sd / math.sqrt(n)


def bootstrap_ci(values: list[float], stat=lambda v: sum(v) / len(v), n_boot: int = 500, alpha: float = 0.05,
                 seed: int = 0) -> tuple[float, float] | None:
    """Percentile bootstrap (deterministic for a seed)."""
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    stats = sorted(stat([values[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))
    lo = stats[int(alpha / 2 * n_boot)]
    hi = stats[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return lo, hi


def calibration_error(trades: list[SimTrade], bins: int = 10) -> tuple[float | None, int]:
    """Expected calibration error between stated confidence (trade.context['confidence'])
    and realized outcome (net_pnl > 0). Returns (ece, n_used)."""
    pairs = [(float(t.context["confidence"]), t.net_pnl > 0) for t in trades
             if t.exit_time is not None and isinstance(t.context.get("confidence"), (int, float))]
    n = len(pairs)
    if n == 0:
        return None, 0
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for p, y in pairs:
        buckets[min(bins - 1, max(0, int(p * bins)))].append((p, y))
    ece = 0.0
    for b in buckets:
        if b:
            conf = sum(p for p, _ in b) / len(b)
            acc = sum(1 for _, y in b if y) / len(b)
            ece += len(b) / n * abs(conf - acc)
    return ece, n


def _closed(trades: list[SimTrade]) -> list[SimTrade]:
    return [t for t in trades if t.exit_time is not None]


def _ratio_progress(observed: float, threshold: float) -> float:
    if threshold <= 0:
        return 1.0 if observed >= threshold else 0.0
    return max(0.0, min(1.0, observed / threshold))


# -- assessment ----------------------------------------------------------------
_GROUP_WEIGHTS = {"data": 0.40, "statistical": 0.45, "operational": 0.15}

_REMEDIES = {
    "historical_trades": "run more historical backtests on this broker's real tick data (Memory A)",
    "oos_trades": "run walk-forward / out-of-sample validation on more periods (Memory B)",
    "virtual_trades": "continue live virtual trading on this broker to collect more trades (Memory C)",
    "virtual_days": "continue live virtual trading for more calendar days",
    "regime_coverage": "collect OOS/virtual evidence across more market regimes",
    "oos_profit_factor": "improve or reject the strategy: out-of-sample profit factor too low",
    "virtual_profit_factor": "improve or reject the strategy: virtual profit factor too low",
    "oos_expectancy": "out-of-sample expectancy after costs is not positive enough",
    "virtual_expectancy": "virtual expectancy after costs is not positive enough",
    "expectancy_ci_lower": "collect more trades: expectancy is not significantly above zero",
    "oos_max_drawdown_pct": "reduce drawdown (out-of-sample) before proceeding",
    "virtual_max_drawdown_pct": "reduce drawdown (virtual) before proceeding",
    "calibration_error": "recalibrate the model: stated confidence does not match realized outcomes",
    "oos_degradation": "investigate overfitting: OOS performance degrades sharply vs historical",
    "operational_checks": "run the System Health agent and resolve failing infrastructure checks",
    "emergency_stop_inactive": "clear the emergency stop after investigating its cause (owner action)",
    "feed_fresh": "restore a fresh market data feed from the broker",
}


def _grant_status(store: MemoryStore) -> dict:
    g = store.kv_get("real_execution_grant")
    if not g:
        return {"present": False}
    return {"present": True, "expired": g.get("expires", 0) < time.time(), "accounts": g.get("accounts", []),
            "max_lots": g.get("max_lots"), "granted_by": g.get("granted_by"),
            "note": "read-only view; the maturity engine never creates or uses grants"}


def assess(store: MemoryStore, broker: str, thresholds: MaturityThresholds | None = None, *,
           strategy_version: str | None = None, operational_checks: dict[str, bool] | None = None,
           last_tick_time: datetime | None = None, now: datetime | None = None) -> MaturityReport:
    """Grade the evidence for one broker (optionally one strategy version).

    `operational_checks` is a name -> passed mapping (e.g. from SystemHealthAgent); when
    omitted the operational stage cannot be reached.
    """
    th = thresholds or MaturityThresholds()
    now = now or utcnow()

    def load(domain: MemoryDomain) -> list[SimTrade]:
        ts = _closed(store.load_trades(domain, broker=broker))
        if strategy_version:
            ts = [t for t in ts if t.strategy_version == strategy_version]
        return ts

    hist, oos, virt = load(MemoryDomain.HISTORICAL), load(MemoryDomain.FORWARD), load(MemoryDomain.VIRTUAL)
    runs = [r for r in store.list_runs() if r["broker"] == broker
            and (strategy_version is None or r["strategy_version"] == strategy_version)]
    m_hist = compute_metrics(hist, th.starting_equity)
    m_oos = compute_metrics(oos, th.starting_equity)
    m_virt = compute_metrics(virt, th.starting_equity)
    gates: list[GateResult] = []

    def ge(name, group, observed, threshold, detail=""):
        gates.append(GateResult(name, group, observed >= threshold, observed, threshold, ">=",
                                _ratio_progress(observed, threshold), detail))

    def le(name, group, observed, threshold, detail=""):
        ok = observed <= threshold
        prog = 1.0 if ok else max(0.0, min(1.0, threshold / observed)) if observed > 0 else 0.0
        gates.append(GateResult(name, group, ok, observed, threshold, "<=", prog, detail))

    # -- data sufficiency
    ge("historical_trades", "data", len(hist), th.min_historical_trades, "Memory A closed trades")
    ge("oos_trades", "data", len(oos), th.min_oos_trades, "Memory B closed trades")
    ge("virtual_trades", "data", len(virt), th.min_virtual_trades, "Memory C closed trades")
    days = 0.0
    if virt:
        days = (max(t.exit_time for t in virt) - min(t.entry_time for t in virt)).total_seconds() / 86400
    ge("virtual_days", "data", round(days, 3), th.min_virtual_days, "span of virtual trading evidence")
    regime_counts: dict[str, int] = {}
    for t in oos + virt:
        r = t.context.get("regime", "unknown")
        regime_counts[r] = regime_counts.get(r, 0) + 1
    covered = sum(1 for r, c in regime_counts.items() if r != "unknown" and c >= th.min_trades_per_regime)
    ge("regime_coverage", "data", covered, th.min_regime_coverage,
       f"regimes with >= {th.min_trades_per_regime} OOS+virtual trades: {regime_counts}")

    # -- statistical validation
    def pf(m):
        v = m["profit_factor"]
        return 1e9 if math.isinf(v) else v

    ge("oos_profit_factor", "statistical", pf(m_oos), th.min_profit_factor)
    ge("virtual_profit_factor", "statistical", pf(m_virt), th.min_profit_factor)
    for name, m, n in (("oos_expectancy", m_oos, len(oos)), ("virtual_expectancy", m_virt, len(virt))):
        ok = n > 0 and m["expectancy"] > th.min_expectancy
        gates.append(GateResult(name, "statistical", ok, m["expectancy"], th.min_expectancy, ">",
                                1.0 if ok else 0.0, f"{n} trades"))
    le("oos_max_drawdown_pct", "statistical", m_oos["max_drawdown_pct"], th.max_drawdown_pct)
    le("virtual_max_drawdown_pct", "statistical", m_virt["max_drawdown_pct"], th.max_drawdown_pct)
    combined = [t.net_pnl for t in oos + virt]
    exp_c, se_c = mean_and_se(combined)
    lower = exp_c - 1.96 * se_c if se_c is not None else None
    if th.require_positive_expectancy_ci:
        ok = lower is not None and lower > 0
        gates.append(GateResult("expectancy_ci_lower", "statistical", ok, lower, 0.0, ">", 1.0 if ok else 0.0,
                                "95% lower bound of combined OOS+virtual expectancy"))
    ece, n_cal = calibration_error(virt)
    if ece is None or n_cal < th.min_calibration_trades:
        gates.append(GateResult("calibration_error", "statistical", False, ece, th.max_calibration_error, "<=",
                                0.0, f"needs >= {th.min_calibration_trades} virtual trades with confidence "
                                     f"(have {n_cal})"))
    else:
        le("calibration_error", "statistical", round(ece, 4), th.max_calibration_error, f"{n_cal} trades")
    h_e, o_e = m_hist["expectancy"], m_oos["expectancy"]
    if hist and oos and h_e > 0:
        ratio = o_e / h_e
        ge("oos_degradation", "statistical", round(ratio, 4), th.max_oos_degradation,
           "OOS expectancy / historical expectancy")
    else:
        gates.append(GateResult("oos_degradation", "statistical", False, None, th.max_oos_degradation, ">=", 0.0,
                                "needs positive historical expectancy and OOS trades"))

    # -- operational
    estop = bool(store.kv_get("emergency_stop", False))
    gates.append(GateResult("emergency_stop_inactive", "operational", not estop, estop, False, "==",
                            0.0 if estop else 1.0))
    if last_tick_time is not None:
        age = (now - last_tick_time).total_seconds()
        le("feed_fresh", "operational", round(age, 3), th.max_tick_age_seconds, "seconds since last tick")
    if operational_checks is None:
        gates.append(GateResult("operational_checks", "operational", False, "not run", "all pass", "==", 0.0,
                                "no system health results supplied"))
    else:
        failed = sorted(k for k, v in operational_checks.items() if not v)
        n_ok = len(operational_checks) - len(failed)
        gates.append(GateResult("operational_checks", "operational", not failed and bool(operational_checks),
                                f"{n_ok}/{len(operational_checks)}", "all pass", "==",
                                n_ok / len(operational_checks) if operational_checks else 0.0,
                                f"failed: {failed}" if failed else ""))

    # -- stages (each requires the previous one)
    by_group = {g: [x for x in gates if x.group == g] for g in _GROUP_WEIGHTS}
    observation_ready = True  # reading the store succeeded; observation is read-only
    data_sufficient = all(x.passed for x in by_group["data"])
    statistically_validated = data_sufficient and all(x.passed for x in by_group["statistical"])
    operationally_ready = statistically_validated and all(x.passed for x in by_group["operational"])

    score = 0.0
    for g, w in _GROUP_WEIGHTS.items():
        xs = by_group[g]
        if xs:
            score += w * sum(x.progress for x in xs) / len(xs)
    score = round(100.0 * score, 1)

    failed = [x.name for x in gates if not x.passed]
    wins = sum(1 for v in combined if v > 0)
    uncertainty = {
        "combined_trades": len(combined),
        "win_rate": wins / len(combined) if combined else None,
        "win_rate_wilson_95": wilson_interval(wins, len(combined)),
        "expectancy": exp_c,
        "expectancy_se": se_c,
        "expectancy_95": (exp_c - 1.96 * se_c, exp_c + 1.96 * se_c) if se_c is not None else None,
        "expectancy_bootstrap_95": bootstrap_ci(combined),
        "per_domain": {
            name: {"trades": m["total_trades"], "win_rate": m["win_rate"],
                   "win_rate_wilson_95": wilson_interval(m["winning_trades"], m["total_trades"]),
                   "expectancy": m["expectancy"], "expectancy_se": mean_and_se([t.net_pnl for t in ts])[1]}
            for name, m, ts in (("historical", m_hist, hist), ("oos", m_oos, oos), ("virtual", m_virt, virt))
        },
        "calibration_error": ece,
    }
    counts = {"historical_trades": len(hist), "oos_trades": len(oos), "virtual_trades": len(virt),
              "runs": len(runs), "run_kinds": sorted({r["kind"] for r in runs}), "regimes": regime_counts}
    return MaturityReport(
        broker=broker, strategy_version=strategy_version, time=now, score=score, gates=gates,
        failed_gates=failed, required_tests=[_REMEDIES.get(n, n) for n in failed], uncertainty=uncertainty,
        counts=counts, observation_ready=observation_ready, data_sufficient=data_sufficient,
        statistically_validated=statistically_validated, operationally_ready=operationally_ready,
        live_authorized=False, owner_grant_status=_grant_status(store),
    )


def assess_all_brokers(store: MemoryStore, thresholds: MaturityThresholds | None = None,
                       **kw) -> dict[str, MaturityReport]:
    """One independent report per broker found in Memory A/B/C or the run log."""
    brokers = {r["broker"] for r in store.list_runs()}
    for d in (MemoryDomain.HISTORICAL, MemoryDomain.FORWARD, MemoryDomain.VIRTUAL):
        brokers |= {t.broker for t in store.load_trades(d)}
    return {b: assess(store, b, thresholds, **kw) for b in sorted(brokers)}
