"""ENGINE B — Walk-forward and out-of-sample validation. Results go to Memory B only.

Each fold has three strictly sequential, non-overlapping segments:
  train      -> candidates learn (exploration allowed)
  validation -> learning frozen; best candidate selected here
  test       -> learning frozen; selected candidate scored on unseen data
Windows can be rolling (fixed-length train) or anchored (train grows from start).
This is historical out-of-sample validation and is labeled as such — it is never
reported as live forward trading.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from ..agents.decision import StrategyParams
from ..config import Settings
from ..domain import MemoryDomain, SymbolSpec, Tick
from ..memory.store import MemoryStore
from .backtest import run_backtest


@dataclass
class WalkForwardConfig:
    train: timedelta
    validation: timedelta
    test: timedelta
    step: timedelta | None = None   # defaults to test length
    anchored: bool = False
    min_validation_trades: int = 5
    max_degradation: float = 0.5    # test expectancy must retain >= 50% of train expectancy (if positive)


@dataclass
class Fold:
    index: int
    train: tuple[datetime, datetime]
    validation: tuple[datetime, datetime]
    test: tuple[datetime, datetime]


@dataclass
class FoldResult:
    fold: Fold
    selected: str | None
    train_metrics: dict
    validation_metrics: dict
    test_metrics: dict
    candidate_scores: dict[str, float]
    notes: list[str] = field(default_factory=list)


@dataclass
class WalkForwardReport:
    folds: list[FoldResult]
    selection_stability: float          # share of folds selecting the modal candidate
    oos_trades: int
    oos_net: float
    oos_expectancy: float
    overfit_flags: list[str]
    verdict: str                        # "pass" | "fail" | "insufficient_data"
    run_ids: list[str]
    label: str = "historical out-of-sample (walk-forward) — NOT live forward trading"


def make_folds(start: datetime, end: datetime, cfg: WalkForwardConfig) -> list[Fold]:
    step = cfg.step or cfg.test
    folds = []
    i = 0
    tr_start = start
    tr_end = start + cfg.train
    while True:
        va_end = tr_end + cfg.validation
        te_end = va_end + cfg.test
        if te_end > end:
            break
        folds.append(Fold(i, (tr_start, tr_end), (tr_end, va_end), (va_end, te_end)))
        i += 1
        tr_end += step
        if not cfg.anchored:
            tr_start += step
    return folds


def _slice(ticks: list[Tick], a: datetime, b: datetime) -> list[Tick]:
    return [t for t in ticks if a <= t.time < b]


def _score(m: dict, min_trades: int) -> float:
    """Validation score: expectancy penalized by drawdown; -inf if too few trades."""
    if m["total_trades"] < min_trades:
        return -math.inf
    return m["expectancy"] - 0.1 * m["max_drawdown"] / max(1, m["total_trades"])


def run_walkforward(settings: Settings, spec: SymbolSpec, ticks: list[Tick], candidates: list[StrategyParams],
                    cfg: WalkForwardConfig, *, store: MemoryStore | None = None, data_source: str = "unknown",
                    seed: int = 0) -> WalkForwardReport:
    if not ticks:
        raise ValueError("no ticks")
    folds = make_folds(ticks[0].time, ticks[-1].time, cfg)
    if not folds:
        return WalkForwardReport([], 0.0, 0, 0.0, 0.0, ["period too short for one fold"], "insufficient_data", [])
    results: list[FoldResult] = []
    run_ids: list[str] = []
    flags: list[str] = []
    selections: list[str] = []
    oos = []
    for fold in folds:
        tr = _slice(ticks, *fold.train)
        va = _slice(ticks, *fold.validation)
        te = _slice(ticks, *fold.test)
        if not (tr and va and te):
            results.append(FoldResult(fold, None, {}, {}, {}, {}, ["empty segment"]))
            continue
        scores: dict[str, float] = {}
        trained = {}
        for p in candidates:
            # Training uses exploration to gather outcomes; validation/test never explore.
            train_params = StrategyParams(**{**asdict(p), "exploration_rate": max(p.exploration_rate, 0.3)})
            bt_tr = run_backtest(settings, spec, tr, params=train_params, learn=True, seed=seed,
                                 data_source=data_source)
            eval_params = StrategyParams(**{**asdict(p), "exploration_rate": 0.0})
            bt_va = run_backtest(settings, spec, va, params=eval_params, model=bt_tr.final_model, learn=False,
                                 seed=seed, data_source=data_source)
            v = p.version()
            scores[v] = _score(bt_va.metrics, cfg.min_validation_trades)
            trained[v] = (eval_params, bt_tr, bt_va)
        best_v = max(scores, key=lambda k: scores[k])
        if scores[best_v] == -math.inf:
            results.append(FoldResult(fold, None, {}, {}, {}, scores,
                                      ["no candidate produced enough validation trades"]))
            continue
        eval_params, bt_tr, bt_va = trained[best_v]
        bt_te = run_backtest(settings, spec, te, params=eval_params, model=bt_tr.final_model, learn=False,
                             seed=seed, data_source=data_source, store=store, domain=MemoryDomain.FORWARD,
                             kind=f"walkforward-fold{fold.index}", account="walkforward")
        run_ids.append(bt_te.run_id)
        selections.append(best_v)
        oos.extend(bt_te.trades)
        notes = []
        tr_e, te_e = bt_tr.metrics["expectancy"], bt_te.metrics["expectancy"]
        if tr_e > 0 and te_e < tr_e * cfg.max_degradation:
            notes.append(f"degradation: train expectancy {tr_e:.2f} -> test {te_e:.2f}")
            flags.append(f"fold {fold.index}: performance degradation out-of-sample")
        if bt_va.metrics["expectancy"] > 0 and te_e <= 0:
            flags.append(f"fold {fold.index}: positive validation but non-positive test (possible overfit)")
        results.append(FoldResult(fold, best_v, bt_tr.metrics, bt_va.metrics, bt_te.metrics, scores, notes))

    stability = 0.0
    if selections:
        modal = max(set(selections), key=selections.count)
        stability = selections.count(modal) / len(selections)
        if len(selections) >= 3 and stability < 0.5:
            flags.append(f"unstable parameter selection (stability {stability:.2f})")
    n = len(oos)
    net = sum(t.net_pnl for t in oos)
    exp = net / n if n else 0.0
    if n < cfg.min_validation_trades * max(1, len(selections)):
        verdict = "insufficient_data"
    elif exp > 0 and not any("overfit" in f or "unstable" in f for f in flags):
        verdict = "pass"
    else:
        verdict = "fail"
    return WalkForwardReport(results, stability, n, net, exp, flags, verdict, run_ids)
