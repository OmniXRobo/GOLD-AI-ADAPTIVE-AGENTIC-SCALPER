from datetime import timedelta

import pytest

from gold_ai.agents.decision import ModelState, StrategyParams, TradingDecisionAgent
from gold_ai.brokers.mock_feed import SYNTHETIC_SOURCE, synthetic_ticks
from gold_ai.domain import MemoryDomain, Side, Tick
from gold_ai.engines.backtest import run_backtest
from gold_ai.engines.live_virtual import LiveVirtualEngine
from gold_ai.engines.metrics import compute_metrics
from gold_ai.engines.walkforward import WalkForwardConfig, make_folds, run_walkforward

EXPLORE = StrategyParams(exploration_rate=0.5, min_samples=10**9)


def ticks(n=40_000, seed=3):
    return list(synthetic_ticks(n, step_seconds=1, seed=seed, drift=0.01, regime_switch_every=4000))


def test_backtest_is_reproducible_and_records(settings, spec, store):
    tk = ticks()
    a = run_backtest(settings, spec, tk, params=EXPLORE, seed=1, data_source=SYNTHETIC_SOURCE, store=store)
    b = run_backtest(settings, spec, tk, params=EXPLORE, seed=1, data_source=SYNTHETIC_SOURCE)
    assert a.metrics["total_trades"] > 0
    assert [t.net_pnl for t in a.trades] == [t.net_pnl for t in b.trades]
    assert a.data_hash == b.data_hash
    assert store.count_trades(MemoryDomain.HISTORICAL) == len(a.trades)
    assert store.count_trades(MemoryDomain.FORWARD) == 0
    run = store.list_runs(MemoryDomain.HISTORICAL)[0]
    assert run["data_source"] == "synthetic" and run["model_version_start"] != run["model_version_end"]


def test_backtest_fills_on_next_tick(settings, spec):
    tk = ticks(20_000)
    r = run_backtest(settings, spec, tk, params=EXPLORE, seed=2)
    times = {t.time for t in tk}
    for tr in r.trades:
        assert tr.entry_time in times
        assert tr.is_estimated_fill
        assert tr.context["exploration"] is True


def test_immature_model_waits_without_exploration(settings, spec):
    r = run_backtest(settings, spec, ticks(20_000), params=StrategyParams(), seed=0)
    assert r.metrics["total_trades"] == 0  # no validated edge => WAIT


def test_learning_changes_model_and_input_not_mutated(settings, spec):
    m = ModelState()
    v0 = m.version()
    r = run_backtest(settings, spec, ticks(), params=EXPLORE, model=m, seed=1)
    assert m.version() == v0
    assert r.model_end != v0
    assert r.final_model.buy.n_updates + r.final_model.sell.n_updates == len(r.trades)


def test_model_roundtrip():
    m = ModelState()
    m.buy.update([0.1] * len(m.buy.w), 1.0)
    m2 = ModelState.from_dict(m.to_dict())
    assert m2.version() == m.version()


def test_metrics_math():
    from datetime import datetime, timezone
    from gold_ai.domain import SimTrade
    T = datetime(2024, 1, 1, tzinfo=timezone.utc)

    def tr(p):
        return SimTrade("x", "b", "a", "XAUUSD", Side.BUY, 1, T, 1, 0, 2, "s", "m", exit_time=T,
                        net_pnl=p, initial_risk_money=10)
    m = compute_metrics([tr(20), tr(-10), tr(-10), tr(30)], 1000)
    assert m["total_trades"] == 4 and m["win_rate"] == 0.5
    assert m["profit_factor"] == pytest.approx(2.5)
    assert m["max_drawdown"] == pytest.approx(20)
    assert m["expectancy"] == pytest.approx(7.5)
    assert m["avg_r_multiple"] == pytest.approx(0.75)


def test_walkforward_folds_dont_overlap(spec):
    tk = ticks(10_000)
    cfg = WalkForwardConfig(timedelta(hours=1), timedelta(minutes=20), timedelta(minutes=20))
    folds = make_folds(tk[0].time, tk[-1].time, cfg)
    assert folds
    for f in folds:
        assert f.train[1] == f.validation[0] and f.validation[1] == f.test[0]
    anchored = make_folds(tk[0].time, tk[-1].time, WalkForwardConfig(**{**cfg.__dict__, "anchored": True}))
    assert all(f.train[0] == tk[0].time for f in anchored)


def test_walkforward_runs_and_writes_memory_b(settings, spec, store):
    tk = ticks(60_000)
    cfg = WalkForwardConfig(timedelta(hours=6), timedelta(hours=2), timedelta(hours=2), min_validation_trades=1)
    cands = [StrategyParams(min_samples=5, min_confidence=0.0), StrategyParams(min_samples=5, min_confidence=0.0,
                                                                                risk_reward=2.0)]
    rep = run_walkforward(settings, spec, tk, cands, cfg, store=store, data_source=SYNTHETIC_SOURCE)
    assert rep.verdict in ("pass", "fail", "insufficient_data")
    assert "NOT live" in rep.label
    assert store.count_trades(MemoryDomain.FORWARD) == rep.oos_trades
    assert store.count_trades(MemoryDomain.HISTORICAL) == 0


class ListSource:
    def __init__(self, ticks):
        self.ticks = list(ticks)
        self.i = 0

    def latest_tick(self, symbol):
        if self.i >= len(self.ticks):
            return None
        t = self.ticks[self.i]
        self.i += 1
        return t


def test_live_virtual_persists_and_resumes(settings, spec, store):
    src = ListSource(ticks(30_000))
    eng = LiveVirtualEngine(settings, spec, src, store, params=EXPLORE)
    for _ in range(15_000):
        eng.poll_once()
    eng._persist()
    v1 = eng.agent.model.version()
    started = eng.status()["learning_started"]
    n_closed = store.count_trades(MemoryDomain.VIRTUAL)
    open_before = len(eng.loop.sim.positions)
    assert eng.loop.stats.ticks == 15_000
    # simulate restart
    eng2 = LiveVirtualEngine(settings, spec, src, store, params=EXPLORE)
    assert eng2.agent.model.version() == v1
    assert eng2.status()["learning_started"] == started
    assert len(eng2.loop.sim.positions) == open_before
    for _ in range(15_000):
        eng2.poll_once()
    assert store.count_trades(MemoryDomain.VIRTUAL) >= n_closed
    assert store.count_trades(MemoryDomain.REAL) == 0


def test_live_virtual_ignores_duplicate_ticks(settings, spec, store):
    t = ticks(1)[0]

    class Same:
        def latest_tick(self, s):
            return t
    eng = LiveVirtualEngine(settings, spec, Same(), store)
    eng.poll_once()
    eng.poll_once()
    assert eng.loop.stats.ticks == 1 and eng.stale_polls == 1


def test_live_virtual_rejects_execution_capable_source(settings, spec, store):
    class Bad:
        def latest_tick(self, s):
            return None

        def order_send(self, r):
            pass
    with pytest.raises(TypeError):
        LiveVirtualEngine(settings, spec, Bad(), store)
