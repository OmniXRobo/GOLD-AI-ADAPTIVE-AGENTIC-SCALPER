"""Research harness: evaluate every setup in the strategy library on the same data, costs and risk rules.

Protocol (docs/AGENTIC_REDESIGN.md §4):
- The period is split chronologically into train / validation / test by time, never shuffled.
- Each setup runs through the shared `TradingLoop` (next-tick bid/ask fills, slippage, commission, swap,
  independent risk veto). Setups have no fitted state, so one causal pass over the whole period is split by
  entry time; a trade only ever uses data observed before its entry.
- Variants (reward:risk grid) are chosen on the *validation* split. The *test* split is scored once, for the
  chosen variant only.
- Each chosen variant is compared with a random-entry baseline that trades at the same frequency with the
  same stop size (in ATR) and reward:risk. A setup that cannot beat random timing adds nothing.
- Verdicts are conservative: fewer than `min_test_trades` test trades is "insufficient_data"; an interval
  that includes zero is "inconclusive"; only a positive interval that also beats the baseline and holds on
  validation is a "candidate" — which still needs walk-forward and forward virtual evidence before any use.
Every setup is reported, including the ones that fail.
"""
from __future__ import annotations

import statistics
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Iterable

from ..config import Settings
from ..domain import MemoryDomain, SimTrade, SymbolSpec, Tick
from ..engines.loop import TradingLoop
from ..engines.metrics import json_safe
from ..instruments import settings_for
from ..market.features import MarketIntelligenceAgent
from ..memory.store import MemoryStore
from ..risk.engine import NewsEvent, RiskEngine
from ..strategies.agent import RuleAgent, RuleParams
from ..strategies.setups import RESEARCH_SETUPS, SETUPS, RandomBaseline
from .stats import r_summary
from .stream import Meter, TickStream

SPLITS = ("train", "validation", "test")


@dataclass
class ResearchConfig:
    train_frac: float = 0.5
    validation_frac: float = 0.25          # test = the rest
    risk_rewards: tuple[float, ...] = (1.0, 1.5, 2.0)
    setups: tuple[str, ...] = RESEARCH_SETUPS
    min_test_trades: int = 30
    min_validation_trades: int = 10
    max_hold_seconds: int = 3600
    starting_equity: float = 10_000.0
    seed: int = 0


@dataclass
class SetupReport:
    setup: str
    family: str
    regime: str
    selected: dict | None                   # chosen RuleParams (dict) or None
    variants: dict[str, dict]               # rr -> {split -> r_summary}
    test: dict
    baseline_test: dict
    by_regime_test: dict
    rejections: dict
    verdict: str
    notes: list[str] = field(default_factory=list)
    run_id: str | None = None


@dataclass
class ResearchReport:
    symbol: str
    broker: str
    data_source: str
    period: tuple[str, str]
    splits: dict[str, tuple[str, str]]
    ticks: int
    m1_bars: int
    setups: list[SetupReport]
    data_hash: str
    label: str = ("historical research on recorded ticks with modelled costs — NOT live or forward results; "
                  "a 'candidate' still needs walk-forward and forward virtual evidence")

    def to_dict(self) -> dict:
        return json_safe(asdict(self))


def split_bounds(ticks: "list[Tick] | TickStream", cfg: ResearchConfig) -> dict[str, tuple[datetime, datetime]]:
    a, z = (ticks.start, ticks.end) if isinstance(ticks, TickStream) else (ticks[0].time, ticks[-1].time)
    span = z - a
    v = a + span * cfg.train_frac
    t = v + span * cfg.validation_frac
    return {"train": (a, v), "validation": (v, t), "test": (t, z)}


def _split_of(t: SimTrade, b: dict[str, tuple[datetime, datetime]]) -> str:
    for s in SPLITS:
        lo, hi = b[s]
        if lo <= t.entry_time < hi or (s == "test" and t.entry_time == hi):
            return s
    return "test"


def _r(t: SimTrade) -> float:
    return t.r_multiple


RESEARCH_BAR_TIMEFRAMES = ("M1", "M5", "M15", "H1")


def run_lanes(settings: Settings, spec: SymbolSpec, ticks: Iterable[Tick],
              lanes: list[tuple[RuleParams, object | None]], *, news: list[NewsEvent] | None = None,
              starting_equity: float = 10_000.0) -> list[tuple[list[SimTrade], RuleAgent]]:
    """Run several independent rule lanes in one pass over the ticks. Lanes share the market agent (bars and
    features) and an indicator cache, but each has its own account, simulator, risk engine and pending order,
    so the result for a lane is identical to running it alone."""
    if not lanes:
        return []
    timeframes = lanes[0][0].timeframes
    market = MarketIntelligenceAgent(timeframes=timeframes, bar_timeframes=RESEARCH_BAR_TIMEFRAMES)
    cache: dict = {}
    loops: list[TradingLoop] = []
    for params, setup in lanes:
        agent = RuleAgent(params, setup, cache)
        risk = RiskEngine.create(settings_for(settings, spec).risk, spec, starting_equity)
        risk.news = list(news or [])
        loops.append(TradingLoop(settings, spec, agent, broker=spec.broker, account="research",
                                 starting_equity=starting_equity, learn=False, simulation=True, risk=risk,
                                 market=market))
    trades: list[list[SimTrade]] = [[] for _ in loops]
    gate = RuleAgent.decide_on_bar_close
    for tick in ticks:
        new_bars = market.on_tick(tick)
        state = market.state(advance=True) if gate in new_bars else None
        for i, lp in enumerate(loops):
            trades[i].extend(lp.process(tick, new_bars, state))
    out = []
    for i, lp in enumerate(loops):
        trades[i].extend(lp.finish())
        out.append((trades[i], lp.agent))
    return out


def run_rules(settings: Settings, spec: SymbolSpec, ticks: list[Tick], params: RuleParams, *,
              setup=None, news: list[NewsEvent] | None = None, starting_equity: float = 10_000.0,
              ) -> tuple[list[SimTrade], RuleAgent]:
    return run_lanes(settings, spec, ticks, [(params, setup)], news=news, starting_equity=starting_equity)[0]


def _by_split(trades: list[SimTrade], b) -> dict[str, list[SimTrade]]:
    out: dict[str, list[SimTrade]] = {s: [] for s in SPLITS}
    for t in trades:
        out[_split_of(t, b)].append(t)
    return out


def verdict(test: dict, validation: dict, baseline: dict, cfg: ResearchConfig) -> tuple[str, list[str]]:
    notes: list[str] = []
    n = test["trades"]
    if n < cfg.min_test_trades:
        return "insufficient_data", [f"{n} test trades < {cfg.min_test_trades} required"]
    e, ci = test["expectancy_r"], test["ci90"]
    if e <= 0 or (ci and ci[1] < 0):
        return "rejected", [f"test expectancy {e:+.3f}R after costs is not positive"]
    if baseline["trades"] and e <= baseline["expectancy_r"]:
        return "rejected", [f"no better than random entry with the same bracket "
                            f"({e:+.3f}R vs {baseline['expectancy_r']:+.3f}R)"]
    if validation["trades"] == 0 or validation["expectancy_r"] <= 0:
        notes.append("validation expectancy not positive")
        return "inconclusive", notes
    if ci is None or ci[0] <= 0:
        return "inconclusive", [f"90% interval {ci[0]:+.3f}..{ci[1]:+.3f}R includes zero" if ci else "no interval"]
    return "candidate", ["positive after costs on validation and test and above random baseline; "
                         "needs walk-forward and forward virtual confirmation"]


def evaluate_setups(settings: Settings, spec: SymbolSpec, ticks: "list[Tick] | TickStream",
                    cfg: ResearchConfig | None = None, *, news: list[NewsEvent] | None = None,
                    store: MemoryStore | None = None, data_source: str = "unknown", progress=None) -> ResearchReport:
    """`ticks` is a list or a re-iterable `TickStream` (read twice: setups, then matched baselines)."""
    cfg = cfg or ResearchConfig()
    stream = ticks if isinstance(ticks, TickStream) else TickStream.from_list(ticks)
    b = split_bounds(stream, cfg)
    reports: list[SetupReport] = []
    for name in cfg.setups:
        if name not in SETUPS:
            raise ValueError(f"unknown setup {name}")
    grid = [(name, rr) for name in cfg.setups for rr in cfg.risk_rewards]
    if progress:
        progress(f"pass 1: {len(grid)} setup variants, {stream.start} -> {stream.end}")
    meter = Meter(stream)
    results = run_lanes(settings, spec, meter,
                        [(RuleParams(setup=n, risk_reward=rr, max_hold_seconds=cfg.max_hold_seconds), None)
                         for n, rr in grid], news=news, starting_equity=cfg.starting_equity)
    by_setup: dict[str, dict[float, tuple[RuleParams, dict[str, list[SimTrade]], RuleAgent]]] = {}
    for (name, rr), (trades, agent) in zip(grid, results):
        by_setup.setdefault(name, {})[rr] = (agent.params, _by_split(trades, b), agent)
    m1_bars, dh, n_ticks = meter.m1_bars, meter.data_hash, meter.count
    if n_ticks == 0:
        raise ValueError("no ticks supplied")
    chosen: dict[str, tuple[float, list[str], dict]] = {}
    for name in cfg.setups:
        runs = by_setup[name]
        variants = {f"{rr:g}": {s: r_summary([_r(t) for t in parts[s]], cfg.seed) for s in SPLITS}
                    for rr, (_, parts, _) in runs.items()}
        # choose on validation only (enough trades); fall back to train and say so
        eligible = [rr for rr in cfg.risk_rewards
                    if variants[f"{rr:g}"]["validation"]["trades"] >= cfg.min_validation_trades]
        notes: list[str] = []
        if eligible:
            best = max(eligible, key=lambda rr: variants[f"{rr:g}"]["validation"]["expectancy_r"])
        else:
            best = max(cfg.risk_rewards, key=lambda rr: variants[f"{rr:g}"]["train"]["expectancy_r"])
            notes.append(f"fewer than {cfg.min_validation_trades} validation trades for every variant; "
                         "chosen on train")
        chosen[name] = (best, notes, variants)

    # pass 2: a random-entry baseline per setup, matched in frequency, stop size (ATR) and reward:risk
    baselines = []
    for name in cfg.setups:
        best = chosen[name][0]
        parts = by_setup[name][best][1]
        all_trades = [t for s in SPLITS for t in parts[s]]
        sl_atrs = [t.context.get("sl_atr") for t in all_trades if t.context.get("sl_atr")]
        prob = len(all_trades) / max(1, m1_bars)
        baselines.append((RuleParams(setup="random_baseline", risk_reward=best, min_stop_atr=0.0,
                                     max_hold_seconds=cfg.max_hold_seconds),
                          RandomBaseline(probability=min(1.0, max(prob, 1e-4)),
                                         sl_atr=statistics.median(sl_atrs) if sl_atrs else 1.0, seed=cfg.seed)))
    if progress:
        progress(f"pass 2: {len(baselines)} matched random baselines")
    bl_results = run_lanes(settings, spec, stream, baselines, news=news, starting_equity=cfg.starting_equity)

    for name, (bl_trades, _) in zip(cfg.setups, bl_results):
        cls = SETUPS[name]
        best, notes, variants = chosen[name]
        params, parts, agent = by_setup[name][best]
        test_trades = parts["test"]
        all_trades = [t for s in SPLITS for t in parts[s]]
        test = variants[f"{best:g}"]["test"]
        validation = variants[f"{best:g}"]["validation"]
        baseline = r_summary([_r(t) for t in _by_split(bl_trades, b)["test"]], cfg.seed)
        regimes: dict[str, dict] = {}
        for t in test_trades:
            g = regimes.setdefault(t.context.get("regime", "unknown"), {"trades": 0, "total_r": 0.0})
            g["trades"] += 1
            g["total_r"] += _r(t)
        v, vnotes = verdict(test, validation, baseline, cfg)
        notes = notes + vnotes
        if len(regimes) <= 1 and test_trades:
            notes.append("test trades cover a single regime")
        run_id = None
        if store is not None:
            run_id = f"research-{uuid.uuid4().hex[:12]}"
            store.save_trades(MemoryDomain.HISTORICAL, all_trades, run_id)
            store.save_run(run_id=run_id, domain=MemoryDomain.HISTORICAL.value, kind="research",
                           broker=spec.broker, symbol=spec.symbol, data_source=data_source, data_hash=dh,
                           period_start=stream.start, period_end=stream.end,
                           strategy_version=params.version(), model_version_start="none",
                           model_version_end="none", params=asdict(params),
                           metrics=json_safe({"verdict": v, "test": test, "validation": validation,
                                              "baseline_test": baseline, "variants": variants,
                                              "splits": {k: [a.isoformat(), z.isoformat()] for k, (a, z) in b.items()},
                                              "notes": notes}))
        reports.append(SetupReport(name, cls.family, cls.regime, asdict(params), variants, test, baseline,
                                   regimes, dict(agent.rejected), v, notes, run_id))
        if progress:
            progress(f"{name}: verdict {v}")
    return ResearchReport(spec.symbol, spec.broker, data_source,
                          (stream.start.isoformat(), stream.end.isoformat()),
                          {k: (a.isoformat(), z.isoformat()) for k, (a, z) in b.items()},
                          n_ticks, m1_bars, reports, dh)


def _fmt_ci(ci) -> str:
    return f"{ci[0]:+.3f}..{ci[1]:+.3f}" if ci else "n/a"


def to_markdown(r: ResearchReport) -> str:
    lines = [f"# Setup research — {r.symbol} ({r.broker})", "",
             f"Data: {r.data_source}, {r.ticks:,} ticks, {r.m1_bars:,} M1 bars, {r.period[0]} → {r.period[1]}",
             f"Splits: " + "; ".join(f"{k} {a[:16]} → {z[:16]}" for k, (a, z) in r.splits.items()),
             f"Data hash: `{r.data_hash}`", "", f"_{r.label}_", "",
             "| Setup | Verdict | RR | Test trades | Test exp. (R) | 90% CI | PF | Max DD (R) | Random baseline (R) | Val. exp. (R) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for s in r.setups:
        t, bl = s.test, s.baseline_test
        rr = s.selected["risk_reward"] if s.selected else "-"
        val = s.variants[f"{rr:g}"]["validation"]["expectancy_r"] if s.selected else 0.0
        pf = f"{t['profit_factor']:.2f}" if t.get("profit_factor") else "n/a"
        lines.append(f"| {s.setup} | **{s.verdict}** | {rr} | {t['trades']} | {t['expectancy_r']:+.3f} | "
                     f"{_fmt_ci(t['ci90'])} | {pf} | {t['max_drawdown_r']:.1f} | {bl['expectancy_r']:+.3f} "
                     f"({bl['trades']}) | {val:+.3f} |")
    lines += ["", "## Notes per setup", ""]
    for s in r.setups:
        rej = ", ".join(f"{k}: {v}" for k, v in s.rejections.items()) or "none"
        lines.append(f"- **{s.setup}** ({s.family}): {'; '.join(s.notes) or '—'}. Rejected signals: {rej}.")
    return "\n".join(lines) + "\n"
