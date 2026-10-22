import time
from datetime import datetime, timedelta, timezone

import pytest

from gold_ai.agents.maturity import (MaturityThresholds, assess, assess_all_brokers, calibration_error,
                                     wilson_interval)
from gold_ai.domain import ExitReason, MemoryDomain, Side, SimTrade

T0 = datetime(2024, 3, 1, tzinfo=timezone.utc)
REGIMES = ("trend_up", "range", "trend_down")


def mk(i, broker="exness", pnl=20.0, conf=0.6, regime="range", strat="strat-a", days_apart=0.25):
    t = T0 + timedelta(days=i * days_apart)
    return SimTrade(f"{broker}-{strat}-{i}-{pnl}-{regime}", broker, "acc", "XAUUSD", Side.BUY, 0.1, t, 2400.0,
                    2397.0, 2404.5, strat, "model-x", exit_time=t + timedelta(minutes=5), exit_price=2401,
                    exit_reason=ExitReason.TAKE_PROFIT if pnl > 0 else ExitReason.STOP_LOSS, net_pnl=pnl,
                    initial_risk_money=30.0, context={"regime": regime, "confidence": conf})


def edge_trades(n, prefix_offset=0, **kw):
    """60% winners at confidence 0.6 (perfectly calibrated), +20 / -10, three regimes."""
    out = []
    for i in range(n):
        win = (i % 10) < 6
        out.append(mk(i + prefix_offset, pnl=20.0 if win else -10.0, regime=REGIMES[i % 3], **kw))
    return out


SMALL = MaturityThresholds(min_historical_trades=30, min_oos_trades=30, min_virtual_trades=60,
                           min_virtual_days=10, min_regime_coverage=3, min_trades_per_regime=10,
                           min_calibration_trades=30, max_calibration_error=0.1)


def populate(store, broker="exness", strat="strat-a"):
    store.save_trades(MemoryDomain.HISTORICAL, edge_trades(40, 0, broker=broker, strat=strat))
    store.save_trades(MemoryDomain.FORWARD, edge_trades(40, 1000, broker=broker, strat=strat))
    store.save_trades(MemoryDomain.VIRTUAL, edge_trades(80, 2000, broker=broker, strat=strat))


def test_empty_store_is_not_ready_and_never_authorized(store):
    r = assess(store, "exness")
    assert r.observation_ready is True
    assert not (r.data_sufficient or r.statistically_validated or r.operationally_ready or r.live_authorized)
    assert 0 <= r.score < 30
    assert "NEVER enables trading" in r.disclaimer
    assert "historical_trades" in r.failed_gates and r.required_tests
    g = {x.name: x for x in r.gates}["virtual_trades"]
    assert g.observed == 0 and g.threshold == 100 and not g.passed


def test_full_evidence_reaches_operational_but_not_live(store):
    populate(store)
    # An owner grant existing does NOT make the maturity engine authorize anything.
    store.kv_set("real_execution_grant", {"accounts": ["1"], "max_lots": 0.1, "expires": time.time() + 3600,
                                          "granted_by": "owner"})
    r = assess(store, "exness", SMALL, operational_checks={"mt5": True, "database": True})
    assert r.data_sufficient and r.statistically_validated and r.operationally_ready, r.failed_gates
    assert r.live_authorized is False
    assert r.owner_grant_status["present"] is True and r.owner_grant_status["expired"] is False
    assert r.score == pytest.approx(100.0)
    assert r.failed_gates == []
    u = r.uncertainty
    lo, hi = u["win_rate_wilson_95"]
    assert lo < 0.6 < hi
    assert u["expectancy"] == pytest.approx(8.0)
    assert u["expectancy_se"] > 0 and u["expectancy_bootstrap_95"][0] < 8.0 < u["expectancy_bootstrap_95"][1]
    assert u["calibration_error"] == pytest.approx(0.0)
    d = r.to_dict()
    assert d["live_authorized"] is False and isinstance(d["time"], str)


def test_operational_stage_requires_health_results_and_no_estop(store):
    populate(store)
    r = assess(store, "exness", SMALL)
    assert r.statistically_validated and not r.operationally_ready
    assert "operational_checks" in r.failed_gates
    store.kv_set("emergency_stop", True)
    r = assess(store, "exness", SMALL, operational_checks={"mt5": True})
    assert not r.operationally_ready and "emergency_stop_inactive" in r.failed_gates


def test_validation_is_per_broker(store):
    populate(store, broker="exness")
    store.save_trades(MemoryDomain.VIRTUAL, edge_trades(5, 9000, broker="equiti"))
    reports = assess_all_brokers(store, SMALL, operational_checks={"x": True})
    assert reports["exness"].statistically_validated
    assert not reports["equiti"].data_sufficient
    assert reports["equiti"].counts["virtual_trades"] == 5


def test_strategy_version_filter(store):
    populate(store, strat="strat-a")
    r = assess(store, "exness", SMALL, strategy_version="strat-b")
    assert r.counts["historical_trades"] == 0 and not r.data_sufficient


def test_losing_strategy_fails_statistical_gates(store):
    losers = [mk(i, pnl=-5.0 if i % 3 else 4.0, regime=REGIMES[i % 3]) for i in range(80)]
    store.save_trades(MemoryDomain.HISTORICAL, edge_trades(40))
    store.save_trades(MemoryDomain.FORWARD, losers[:40])
    store.save_trades(MemoryDomain.VIRTUAL, [mk(i + 500, pnl=t.net_pnl, regime=t.context["regime"])
                                             for i, t in enumerate(losers)])
    r = assess(store, "exness", SMALL, operational_checks={"x": True})
    assert r.data_sufficient and not r.statistically_validated
    assert {"oos_profit_factor", "virtual_expectancy", "expectancy_ci_lower"} <= set(r.failed_gates)


def test_stat_helpers():
    lo, hi = wilson_interval(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    assert wilson_interval(0, 0) == (0.0, 1.0)
    # overconfident: says 0.9, wins 50%
    ts = [mk(i, pnl=10 if i % 2 else -10, conf=0.9) for i in range(20)]
    ece, n = calibration_error(ts)
    assert n == 20 and ece == pytest.approx(0.4)
