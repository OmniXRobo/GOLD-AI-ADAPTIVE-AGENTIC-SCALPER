from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone

import pytest

from gold_ai.agents.decision import ModelState, StrategyParams
from gold_ai.agents.self_healing import (HISTORY_KEY, PARAM_BOUNDS, DeteriorationThresholds, SelfHealingAgent,
                                         detect_deterioration, diagnose, generate_candidates,
                                         win_rate_drop_pvalue)
from gold_ai.brokers.mock_feed import synthetic_ticks
from gold_ai.domain import Side, SimTrade, Tick
from gold_ai.engines.walkforward import WalkForwardConfig
from gold_ai.security.auth import User

T0 = datetime(2024, 5, 1, tzinfo=timezone.utc)
OWNER, OPERATOR = User("owner", "owner"), User("op", "operator")


def mk(i, pnl, conf=0.6, cost=1.0, atr=1.0):
    t = T0 + timedelta(minutes=10 * i)
    return SimTrade(f"t{i}", "mock", "a", "XAUUSD", Side.BUY, 0.1, t, 2400, 2397, 2404, "s", "m",
                    exit_time=t + timedelta(minutes=5), net_pnl=pnl, commission=cost,
                    context={"confidence": conf, "features": {"atr_m5": atr}})


def baseline(n=60):
    return [mk(i, 20 if i % 10 < 6 else -10) for i in range(n)]


def test_detects_expectancy_and_win_rate_drop():
    recent = [mk(1000 + i, 20 if i % 10 < 2 else -10) for i in range(60)]
    rep = detect_deterioration(baseline(), recent)
    assert rep.sufficient_data
    assert {"expectancy_drop", "win_rate_drop"} <= rep.kinds()
    assert any("edge decay" in c for c in diagnose(rep))


def test_detects_costs_volatility_calibration():
    recent = [mk(1000 + i, 20 if i % 10 < 6 else -10, conf=0.95, cost=3.0, atr=2.5) for i in range(60)]
    rep = detect_deterioration(baseline(), recent)
    assert {"cost_increase", "volatility_regime_change", "calibration_drift"} <= rep.kinds()
    assert "expectancy_drop" not in rep.kinds()


def test_healthy_recent_has_no_findings():
    rep = detect_deterioration(baseline(), [mk(1000 + i, 20 if i % 10 < 6 else -10) for i in range(60)])
    assert not rep.deteriorated


def test_data_gaps_stale_ticks_and_errors():
    ticks = [Tick(T0, 1, 1.1), Tick(T0 + timedelta(seconds=1), 1, 1.1), Tick(T0 + timedelta(seconds=500), 1, 1.1)]
    rep = detect_deterioration([], [], ticks=ticks, now=T0 + timedelta(seconds=900),
                               error_counters={"mt5_poll": 9, "db": 1})
    assert {"data_gap", "stale_ticks", "errors"} == rep.kinds()
    assert not rep.sufficient_data


def test_pvalue_direction():
    assert win_rate_drop_pvalue(60, 100, 30, 100) < 0.001
    assert win_rate_drop_pvalue(30, 100, 60, 100) > 0.99


def test_candidates_are_bounded_and_never_raise_risk():
    inc = StrategyParams(min_confidence=0.6, exploration_rate=0.0)
    rep = detect_deterioration(baseline(), [mk(1000 + i, 20 if i % 10 < 6 else -10, conf=0.95, cost=3.0, atr=2.5)
                                            for i in range(60)])
    cands = generate_candidates(inc, rep, max_candidates=8, seed=3)
    assert 1 <= len(cands) <= 8
    assert len({c.version() for c in cands}) == len(cands) and inc.version() not in {c.version() for c in cands}
    base = asdict(inc)
    for c in cands:
        d = asdict(c)
        assert set(d) == set(base)                      # no new knobs (lot sizing is not a strategy param)
        assert c.min_confidence >= inc.min_confidence
        assert c.exploration_rate <= inc.exploration_rate
        for k, (lo, hi) in PARAM_BOUNDS.items():
            assert lo <= d[k] <= hi
            if base[k]:
                assert abs(d[k] / base[k] - 1) <= 0.25 + 1e-6
    assert not any("risk" in f.name and "reward" not in f.name for f in fields(StrategyParams))


@dataclass
class FakeBT:
    metrics: dict
    final_model: ModelState = field(default_factory=ModelState)


@dataclass
class FakeWF:
    verdict: str
    oos_expectancy: float
    oos_trades: int = 30
    run_ids: list = field(default_factory=lambda: ["wf-1"])


def stub_agent(settings, spec, store, good_version_holder):
    def bt(settings, spec, ticks, *, params, **kw):
        good = params.version() == good_version_holder[0]
        return FakeBT({"total_trades": 40, "expectancy": 5.0 if good else -1.0})

    def wf(settings, spec, ticks, cands, cfg, **kw):
        good = cands[0].version() == good_version_holder[0]
        return FakeWF("pass" if good else "fail", 3.0 if good else -0.5)
    return SelfHealingAgent(settings, spec, store, backtest_fn=bt, walkforward_fn=wf)


WF = WalkForwardConfig(timedelta(minutes=30), timedelta(minutes=10), timedelta(minutes=10), min_validation_trades=1)


def bad_recent():
    return [mk(1000 + i, 20 if i % 10 < 2 else -10) for i in range(60)]


def test_cycle_registers_validated_never_approved(settings, spec, store):
    inc = StrategyParams()
    rep = detect_deterioration(baseline(), bad_recent())
    holder = [generate_candidates(inc, rep, 4, 0)[1].version()]
    agent = stub_agent(settings, spec, store, holder)
    ticks = list(synthetic_ticks(50))
    res = agent.run_cycle(inc, ticks, baseline(), bad_recent(), WF, incumbent_version="v-inc", max_candidates=4)
    assert res.action == "evaluated" and len(res.registered) == 1
    m = store.get_model(res.registered[0])
    assert m["stage"] == "validated" and m["parent_version"] == "v-inc" and m["strategy_version"] == holder[0]
    assert all(x["stage"] != "approved" for x in store.list_models())
    failed = [c for c in res.candidates if not c.passed]
    assert failed and all(c.reasons for c in failed)
    hist = store.kv_get(HISTORY_KEY)
    assert len(hist) == 1 and hist[0]["registered"] == res.registered
    assert any(a["action"] == "self_healing_cycle" for a in store.audit_log())


def test_no_deterioration_no_action_and_history_is_append_only(settings, spec, store):
    agent = stub_agent(settings, spec, store, [""])
    healthy = [mk(1000 + i, 20 if i % 10 < 6 else -10) for i in range(60)]
    r1 = agent.run_cycle(StrategyParams(), list(synthetic_ticks(10)), baseline(), healthy, WF)
    r2 = agent.run_cycle(StrategyParams(), list(synthetic_ticks(10)), baseline(), bad_recent(), WF)
    assert r1.action == "no_action" and r2.action == "evaluated" and not r2.registered
    hist = agent.history()
    assert [h["outcome"] for h in hist] == ["no_action", "evaluated"]


def test_infrastructure_only_problem_does_not_touch_strategy(settings, spec, store):
    agent = stub_agent(settings, spec, store, [""])
    r = agent.run_cycle(StrategyParams(), list(synthetic_ticks(10)), [], [], WF, error_counters={"mt5": 50})
    assert r.action == "no_action" and "infrastructure" in r.note


def test_promote_and_rollback_require_owner(settings, spec, store):
    agent = SelfHealingAgent(settings, spec, store)
    for v in ("v1", "v2"):
        store.register_model(v, "s", {}, {}, parent="v0", stage="validated")
    with pytest.raises(PermissionError):
        agent.promote("v1", OPERATOR)
    assert store.get_model("v1")["stage"] == "validated"
    agent.promote("v1", OWNER)
    assert store.get_model("v1")["stage"] == "approved" and store.kv_get("active_model_version") == "v1"
    agent.promote("v2", OWNER)
    assert store.get_model("v1")["stage"] == "retired" and store.get_model("v2")["stage"] == "approved"
    with pytest.raises(ValueError):
        agent.promote("v1", OWNER)               # retired cannot be promoted, only rolled back
    with pytest.raises(PermissionError):
        agent.rollback("v1", OPERATOR)
    agent.rollback("v1", OWNER)
    assert store.get_model("v1")["stage"] == "approved" and store.get_model("v2")["stage"] == "retired"
    assert store.kv_get("active_model_version") == "v1"
    actions = [a["action"] for a in store.audit_log()]
    assert "self_healing_promote" in actions and "self_healing_rollback" in actions
    assert [h["action"] for h in agent.history()] == ["promote", "promote", "rollback"]


def test_real_pipeline_runs_end_to_end(settings, spec, store):
    """Uses the real backtest + walk-forward engines on a small synthetic set."""
    ticks = list(synthetic_ticks(6000, step_seconds=1, seed=5, drift=0.01, regime_switch_every=1500))
    agent = SelfHealingAgent(settings, spec, store, min_backtest_trades=0, min_improvement=-1e9)
    inc = StrategyParams(exploration_rate=0.3, min_samples=10**9, min_confidence=0.0)
    res = agent.run_cycle(inc, ticks, [], [], WF, force=True, max_candidates=2, incumbent_version="v-inc")
    assert res.action == "evaluated" and len(res.candidates) == 2
    assert res.incumbent_walkforward["verdict"] in ("pass", "fail", "insufficient_data")
    for m in store.list_models():
        assert m["stage"] == "validated" and m["parent"] == "v-inc"
