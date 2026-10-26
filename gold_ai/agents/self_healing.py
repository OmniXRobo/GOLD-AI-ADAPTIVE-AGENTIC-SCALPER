"""Self-Healing Agent: detect deterioration, diagnose, and propose validated repairs.

Pipeline (never skips a stage, never touches live trading):
  detect (recent vs baseline trades, data quality, error counters)
  -> diagnose likely causes
  -> generate bounded StrategyParams variations (no martingale, no grid, no risk increase:
     risk % lives in RiskConfig, which this agent cannot change)
  -> backtest candidates + incumbent on recent history (Memory A)
  -> walk-forward candidates + incumbent (Memory B)
  -> register candidates that beat the incumbent as stage "validated" (parent-linked)

Nothing is ever promoted to "approved" automatically: `promote` and `rollback` require
the owner role and are audited. A self-healing history is kept append-only in
store.kv["self_healing_history"] and mirrored to the audit log.
"""
from __future__ import annotations

import json
import math
import random
import statistics
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

from ..config import Settings
from ..domain import SimTrade, SymbolSpec, Tick, utcnow
from ..engines.backtest import run_backtest
from ..engines.walkforward import WalkForwardConfig, run_walkforward
from ..memory.store import MemoryStore
from ..strategies import investigation
from .decision import ModelState, StrategyParams
from .maturity import calibration_error

HISTORY_KEY = "self_healing_history"
ACTIVE_MODEL_KEY = "active_model_version"

# Hard bounds for every tunable parameter. Candidates are clipped into these ranges.
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "sl_atr_mult": (0.8, 3.0),
    "risk_reward": (1.2, 3.0),
    "trailing_start_r": (0.5, 2.0),
    "trailing_distance_r": (0.4, 1.5),
    "min_confidence": (0.5, 0.8),
    "momentum_threshold": (0.1, 1.0),
    "reversion_distance_atr": (0.2, 1.5),
    "max_hold_seconds": (300, 4 * 3600),
}
# Swing trades are held for days, so their hold-time range differs; everything else is shared.
STYLE_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "swing": {"max_hold_seconds": (4 * 3600, 7 * 86400)},
}
MAX_RELATIVE_STEP = 0.25   # no single perturbation moves a parameter by more than 25%


@dataclass
class DeteriorationThresholds:
    min_trades_each: int = 20
    expectancy_drop_frac: float = 0.5        # recent < baseline * (1 - x), or turns non-positive
    win_rate_alpha: float = 0.05             # one-sided two-proportion z-test
    cost_increase_frac: float = 0.25
    volatility_change_ratio: float = 1.5     # either direction
    calibration_drift: float = 0.10
    max_tick_gap_seconds: float = 60.0
    max_tick_age_seconds: float = 30.0
    max_errors: int = 5


@dataclass
class Finding:
    kind: str
    severity: str          # warn | critical
    observed: float | None
    baseline: float | None
    detail: str


@dataclass
class DeteriorationReport:
    findings: list[Finding]
    recent_trades: int
    baseline_trades: int
    sufficient_data: bool

    @property
    def deteriorated(self) -> bool:
        return bool(self.findings)

    def kinds(self) -> set[str]:
        return {f.kind for f in self.findings}


# -- detection -----------------------------------------------------------------
def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def win_rate_drop_pvalue(base_wins: int, base_n: int, rec_wins: int, rec_n: int) -> float:
    """One-sided p-value that the recent win rate is lower than baseline (pooled z-test)."""
    if base_n == 0 or rec_n == 0:
        return 1.0
    p1, p2 = base_wins / base_n, rec_wins / rec_n
    p = (base_wins + rec_wins) / (base_n + rec_n)
    se = math.sqrt(p * (1 - p) * (1 / base_n + 1 / rec_n))
    if se == 0:
        return 0.0 if p2 < p1 else 1.0
    return _norm_sf((p1 - p2) / se)


def _cost(t: SimTrade) -> float:
    return t.commission + t.spread_cost + t.slippage_cost - min(0.0, t.swap)


def _vol(t: SimTrade) -> float | None:
    f = t.context.get("features") or {}
    if isinstance(f.get("atr_m5"), (int, float)) and f["atr_m5"] > 0:
        return float(f["atr_m5"])
    d = abs(t.entry_price - t.stop_loss)
    return d if d > 0 else None


def detect_deterioration(baseline: list[SimTrade], recent: list[SimTrade], *, ticks: list[Tick] | None = None,
                         now: datetime | None = None, error_counters: dict[str, int] | None = None,
                         thresholds: DeteriorationThresholds | None = None) -> DeteriorationReport:
    th = thresholds or DeteriorationThresholds()
    base = [t for t in baseline if t.exit_time is not None]
    rec = [t for t in recent if t.exit_time is not None]
    out: list[Finding] = []
    enough = len(base) >= th.min_trades_each and len(rec) >= th.min_trades_each
    if enough:
        be = statistics.fmean(t.net_pnl for t in base)
        re = statistics.fmean(t.net_pnl for t in rec)
        if (be > 0 and re < be * (1 - th.expectancy_drop_frac)) or (be > 0 and re <= 0):
            out.append(Finding("expectancy_drop", "critical" if re <= 0 else "warn", re, be,
                               f"rolling expectancy {re:.2f} vs baseline {be:.2f}"))
        bw, rw = sum(t.net_pnl > 0 for t in base), sum(t.net_pnl > 0 for t in rec)
        pv = win_rate_drop_pvalue(bw, len(base), rw, len(rec))
        if pv < th.win_rate_alpha:
            out.append(Finding("win_rate_drop", "warn", rw / len(rec), bw / len(base),
                               f"win rate drop significant (one-sided p={pv:.4f})"))
        bc, rc = statistics.fmean(_cost(t) for t in base), statistics.fmean(_cost(t) for t in rec)
        if bc > 0 and rc > bc * (1 + th.cost_increase_frac):
            out.append(Finding("cost_increase", "warn", rc, bc, f"cost per trade {rc:.2f} vs {bc:.2f}"))
        bv = [v for t in base if (v := _vol(t))]
        rv = [v for t in rec if (v := _vol(t))]
        if bv and rv:
            ratio = statistics.median(rv) / statistics.median(bv)
            if ratio >= th.volatility_change_ratio or ratio <= 1 / th.volatility_change_ratio:
                out.append(Finding("volatility_regime_change", "warn", ratio, 1.0,
                                   f"median volatility ratio recent/baseline = {ratio:.2f}"))
        be_c, nb = calibration_error(base)
        re_c, nr = calibration_error(rec)
        if be_c is not None and re_c is not None and nb >= th.min_trades_each and nr >= th.min_trades_each:
            if re_c - be_c > th.calibration_drift:
                out.append(Finding("calibration_drift", "warn", re_c, be_c,
                                   f"calibration error {re_c:.3f} vs baseline {be_c:.3f}"))
    if ticks:
        gaps = [(b.time - a.time).total_seconds() for a, b in zip(ticks, ticks[1:])]
        mx = max(gaps, default=0.0)
        if mx > th.max_tick_gap_seconds:
            out.append(Finding("data_gap", "warn", mx, th.max_tick_gap_seconds,
                               f"{sum(g > th.max_tick_gap_seconds for g in gaps)} gaps, max {mx:.0f}s"))
        if now is not None:
            age = (now - ticks[-1].time).total_seconds()
            if age > th.max_tick_age_seconds:
                out.append(Finding("stale_ticks", "critical", age, th.max_tick_age_seconds,
                                   f"last tick {age:.0f}s old"))
    for name, n in (error_counters or {}).items():
        if n > th.max_errors:
            out.append(Finding("errors", "critical", float(n), float(th.max_errors), f"{name}: {n} errors"))
    return DeteriorationReport(out, len(rec), len(base), enough)


_CAUSES = {
    "expectancy_drop": "edge decay: market behaviour no longer matches what the model learned",
    "win_rate_drop": "entry signal quality degraded (regime shift or stale model)",
    "cost_increase": "broker costs rose (wider spreads / commission / slippage) — edge may be eaten by costs",
    "volatility_regime_change": "volatility regime changed; ATR-scaled stops and targets may be mis-sized",
    "calibration_drift": "model confidence no longer matches outcomes; calibration needs re-learning",
    "data_gap": "market data gaps — feed/connectivity problem, results on this period are unreliable",
    "stale_ticks": "feed is stale — connector or terminal problem, not a strategy problem",
    "errors": "software/infrastructure errors — check System Health before changing the strategy",
}


def diagnose(report: DeteriorationReport) -> list[str]:
    causes = [_CAUSES[k] for k in sorted(report.kinds()) if k in _CAUSES]
    if not report.sufficient_data:
        causes.append("insufficient recent/baseline trades for statistical comparison")
    return causes


# -- candidate generation ---------------------------------------------------------
def _clip(name: str, value: float, style: str = "scalp"):
    lo, hi = STYLE_BOUNDS.get(style, {}).get(name, PARAM_BOUNDS[name])
    v = min(hi, max(lo, value))
    return int(round(v)) if name == "max_hold_seconds" else round(v, 4)


def _perturb(base: StrategyParams, changes: dict[str, float]) -> StrategyParams:
    d = asdict(base)
    for k, factor in changes.items():
        factor = max(1 - MAX_RELATIVE_STEP, min(1 + MAX_RELATIVE_STEP, factor))
        d[k] = _clip(k, d[k] * factor, base.style)
    # Never increase exploration (it only ever applies in simulation anyway).
    d["exploration_rate"] = min(d["exploration_rate"], base.exploration_rate)
    # Confidence floor may only rise.
    d["min_confidence"] = max(d["min_confidence"], base.min_confidence)
    return StrategyParams(**d)


def generate_candidates(incumbent: StrategyParams, report: DeteriorationReport | None = None,
                        max_candidates: int = 6, seed: int = 0) -> list[StrategyParams]:
    """Bounded, deterministic perturbations. Lot sizing / risk % is NOT a StrategyParams field
    and therefore can never be changed here (no martingale, grid or recovery sizing)."""
    kinds = report.kinds() if report else set()
    plans: list[dict[str, float]] = []
    if "volatility_regime_change" in kinds:
        plans += [{"sl_atr_mult": 1.2}, {"sl_atr_mult": 0.85}]
    if "cost_increase" in kinds:
        plans += [{"risk_reward": 1.2, "sl_atr_mult": 1.15}]
    if kinds & {"calibration_drift", "win_rate_drop", "expectancy_drop"}:
        plans += [{"min_confidence": 1.1}, {"momentum_threshold": 1.2, "reversion_distance_atr": 0.85}]
    plans += [{"risk_reward": 1.15}, {"risk_reward": 0.9}, {"trailing_start_r": 1.2, "trailing_distance_r": 0.9},
              {"max_hold_seconds": 0.8}]
    rng = random.Random(seed)
    for _ in range(4):
        keys = rng.sample(sorted(PARAM_BOUNDS), 2)
        plans.append({k: 1 + rng.uniform(-0.15, 0.15) for k in keys})
    out: list[StrategyParams] = []
    seen = {incumbent.version()}
    for plan in plans:
        c = _perturb(incumbent, plan)
        if c.version() not in seen:
            seen.add(c.version())
            out.append(c)
        if len(out) >= max_candidates:
            break
    return out


# -- pipeline -------------------------------------------------------------------
@dataclass
class CandidateEvaluation:
    params: dict
    strategy_version: str
    backtest_metrics: dict
    walkforward_verdict: str | None = None
    walkforward_oos_expectancy: float | None = None
    walkforward_oos_trades: int = 0
    passed: bool = False
    registered_version: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class HealingCycleResult:
    cycle_id: str
    time: datetime
    deterioration: DeteriorationReport
    diagnosis: list[str]
    action: str                       # no_action | evaluated
    incumbent_version: str | None
    incumbent_backtest: dict | None = None
    incumbent_walkforward: dict | None = None
    candidates: list[CandidateEvaluation] = field(default_factory=list)
    registered: list[str] = field(default_factory=list)
    note: str = "validated candidates require an owner promotion; nothing was activated"


def _json(x):
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return None if math.isnan(x) else "inf"
    if isinstance(x, dict):
        return {str(k): _json(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json(v) for v in x]
    return x


def model_scope(m: dict) -> tuple[str | None, str | None, str]:
    """(broker, symbol, style) a registered model was validated for, read from its evidence notes.
    Models registered before trade styles existed have no symbol and count as scalping."""
    try:
        n = json.loads(m.get("notes") or "{}")
    except (TypeError, ValueError):
        n = {}
    if not isinstance(n, dict):
        n = {}
    style = n.get("style") or (m.get("params") or {}).get("style") or "scalp"
    return n.get("broker"), n.get("symbol"), style


class SelfHealingAgent:
    def __init__(self, settings: Settings, spec: SymbolSpec, store: MemoryStore, *,
                 thresholds: DeteriorationThresholds | None = None, min_backtest_trades: int = 5,
                 min_improvement: float = 0.0, persist_runs: bool = True,
                 backtest_fn: Callable = run_backtest, walkforward_fn: Callable = run_walkforward):
        self.settings, self.spec, self.store = settings, spec, store
        self.thresholds = thresholds or DeteriorationThresholds()
        self.min_backtest_trades = min_backtest_trades
        self.min_improvement = min_improvement
        self.persist_runs = persist_runs
        self._bt = backtest_fn
        self._wf = walkforward_fn
        self._style = "scalp"

    # -- history -----------------------------------------------------------------
    def _append_history(self, entry: dict, actor: str, action: str) -> None:
        hist = list(self.store.kv_get(HISTORY_KEY, []) or [])
        entry = _json(dict(entry, time=utcnow().isoformat(), actor=actor, action=action))
        hist.append(entry)
        self.store.kv_set(HISTORY_KEY, hist)
        self.store.audit(actor, f"self_healing_{action}", entry)

    def history(self) -> list[dict]:
        return list(self.store.kv_get(HISTORY_KEY, []) or [])

    # -- cycle --------------------------------------------------------------------
    def run_cycle(self, incumbent: StrategyParams, recent_ticks: list[Tick], baseline_trades: list[SimTrade],
                  recent_trades: list[SimTrade], wf_cfg: WalkForwardConfig, *,
                  incumbent_version: str | None = None, model: ModelState | None = None, force: bool = False,
                  error_counters: dict[str, int] | None = None, now: datetime | None = None,
                  max_candidates: int = 4, seed: int = 0, data_source: str = "unknown",
                  actor: str = "self_healing", feed_ticks: list[Tick] | None = None) -> HealingCycleResult:
        # feed_ticks: the window checked for data gaps / staleness (default: recent_ticks). The scheduled
        # cycle passes only the last minutes so normal daily/weekend market closures are not flagged.
        self._style = incumbent.style
        rep = detect_deterioration(baseline_trades, recent_trades,
                                   ticks=recent_ticks if feed_ticks is None else feed_ticks, now=now,
                                   error_counters=error_counters, thresholds=self.thresholds)
        diag = diagnose(rep)
        cycle = HealingCycleResult(f"heal-{uuid.uuid4().hex[:12]}", utcnow(), rep, diag, "no_action",
                                   incumbent_version)
        infra_only = rep.kinds() and rep.kinds() <= {"data_gap", "stale_ticks", "errors"}
        if (not rep.deteriorated and not force) or (infra_only and not force) or not recent_ticks:
            if infra_only:
                cycle.note = "infrastructure problem only: strategy unchanged, see System Health"
            self._record(cycle, actor)
            return cycle

        cycle.action = "evaluated"
        store = self.store if self.persist_runs else None
        bt_kw = dict(model=model, learn=False, seed=seed, data_source=data_source, store=store,
                     kind="self_healing_backtest", account="self_healing")
        inc_bt = self._bt(self.settings, self.spec, recent_ticks, params=incumbent, **bt_kw)
        cycle.incumbent_backtest = _json(inc_bt.metrics)
        inc_wf = self._wf(self.settings, self.spec, recent_ticks, [incumbent], wf_cfg, store=store,
                          data_source=data_source, seed=seed)
        cycle.incumbent_walkforward = {"verdict": inc_wf.verdict, "oos_expectancy": inc_wf.oos_expectancy,
                                       "oos_trades": inc_wf.oos_trades}

        for cand in generate_candidates(incumbent, rep, max_candidates, seed):
            ev = CandidateEvaluation(asdict(cand), cand.version(), {})
            bt = self._bt(self.settings, self.spec, recent_ticks, params=cand, **bt_kw)
            ev.backtest_metrics = _json(bt.metrics)
            m = bt.metrics
            if m["total_trades"] < self.min_backtest_trades:
                ev.reasons.append(f"backtest trades {m['total_trades']} < {self.min_backtest_trades}")
            elif m["expectancy"] <= inc_bt.metrics["expectancy"] + self.min_improvement:
                ev.reasons.append("backtest expectancy does not beat incumbent")
            if ev.reasons:
                cycle.candidates.append(ev)
                continue
            wf = self._wf(self.settings, self.spec, recent_ticks, [cand], wf_cfg, store=store,
                          data_source=data_source, seed=seed)
            ev.walkforward_verdict, ev.walkforward_oos_expectancy = wf.verdict, wf.oos_expectancy
            ev.walkforward_oos_trades = wf.oos_trades
            if wf.verdict != "pass":
                ev.reasons.append(f"walk-forward verdict {wf.verdict}")
            if wf.oos_expectancy <= inc_wf.oos_expectancy + self.min_improvement:
                ev.reasons.append("walk-forward OOS expectancy does not beat incumbent")
            if not ev.reasons:
                ev.passed = True
                version = f"heal-{cand.version()[6:]}-{uuid.uuid4().hex[:6]}"
                state = (bt.final_model.to_dict() if getattr(bt, "final_model", None) is not None
                         else (model or ModelState()).to_dict())
                evidence = {"cycle": cycle.cycle_id, "broker": self.spec.broker, "symbol": self.spec.symbol,
                            "style": cand.style, "diagnosis": diag, "backtest": ev.backtest_metrics,
                            "walkforward": {"verdict": wf.verdict, "oos_expectancy": wf.oos_expectancy,
                                            "oos_trades": wf.oos_trades, "run_ids": list(wf.run_ids)},
                            "incumbent": cycle.incumbent_walkforward}
                self.store.register_model(version, cand.version(), asdict(cand), state, parent=incumbent_version,
                                          stage="validated", notes=json.dumps(_json(evidence)))
                ev.registered_version = version
                cycle.registered.append(version)
            cycle.candidates.append(ev)
        self._record(cycle, actor)
        return cycle

    def _record(self, c: HealingCycleResult, actor: str) -> None:
        self._append_history({
            "cycle_id": c.cycle_id, "broker": self.spec.broker, "symbol": self.spec.symbol,
            "style": self._style, "outcome": c.action, "findings": [asdict(f) for f in c.deterioration.findings],
            "diagnosis": c.diagnosis, "incumbent": c.incumbent_version,
            "incumbent_walkforward": c.incumbent_walkforward,
            "candidates": [{"strategy_version": e.strategy_version, "passed": e.passed, "reasons": e.reasons,
                            "registered_version": e.registered_version} for e in c.candidates],
            "registered": c.registered, "note": c.note,
        }, actor, "cycle")

    # -- owner actions ---------------------------------------------------------------
    @staticmethod
    def _require_owner(user) -> None:
        if getattr(user, "role", None) != "owner":
            raise PermissionError("only the owner can change the approved model")

    def _check_investigation(self, m: dict) -> None:
        for v in (m.get("strategy_version"), m.get("version")):
            if (b := investigation.blocking(self.store, v)) is not None:
                raise ValueError(f"strategy {v} is under investigation ({b['target']}) and cannot be promoted")

    def _approved(self, like: dict | None = None) -> list[str]:
        """Approved versions; with `like`, only those for the same symbol and trade style (one approved
        strategy per engine, so promoting a gold swing version does not retire the BTCUSD scalping one)."""
        scope = model_scope(like) if like else None
        return [m["version"] for m in self.store.list_models()
                if m["stage"] == "approved" and (scope is None or model_scope(m) == scope)]

    def promote(self, version: str, owner_user) -> dict:
        """Owner-only: validated -> approved. The previous approved model is retired.
        Approval selects the model for signals/simulation; it does NOT authorize real trading."""
        self._require_owner(owner_user)
        m = self.store.get_model(version)
        if m is None:
            raise KeyError(version)
        if m["stage"] != "validated":
            raise ValueError(f"only 'validated' models can be promoted (stage is {m['stage']!r})")
        self._check_investigation(m)
        previous = self._approved(m)
        for v in previous:
            self.store.set_model_stage(v, "retired", owner_user.username, f"superseded by {version}")
        self.store.set_model_stage(version, "approved", owner_user.username, "owner promotion")
        self.store.kv_set(ACTIVE_MODEL_KEY, version)
        entry = {"version": version, "previous": previous}
        self._append_history(entry, owner_user.username, "promote")
        return entry

    def rollback(self, to_version: str, owner_user) -> dict:
        """Owner-only: re-approve a previously approved/validated version, retiring the current one."""
        self._require_owner(owner_user)
        m = self.store.get_model(to_version)
        if m is None:
            raise KeyError(to_version)
        if m["stage"] not in ("retired", "validated", "approved"):
            raise ValueError(f"cannot roll back to a model in stage {m['stage']!r}")
        self._check_investigation(m)
        previous = [v for v in self._approved(m) if v != to_version]
        for v in previous:
            self.store.set_model_stage(v, "retired", owner_user.username, f"rollback to {to_version}")
        if m["stage"] != "approved":
            self.store.set_model_stage(to_version, "approved", owner_user.username, "owner rollback")
        self.store.kv_set(ACTIVE_MODEL_KEY, to_version)
        entry = {"version": to_version, "previous": previous}
        self._append_history(entry, owner_user.username, "rollback")
        return entry
