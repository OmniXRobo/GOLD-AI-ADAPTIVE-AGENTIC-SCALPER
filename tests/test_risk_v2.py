"""Risk engine v2 rules (docs/AGENTIC_REDESIGN.md §5): each rule blocks when it should and allows otherwise."""
from datetime import datetime, timedelta, timezone

import pytest

from gold_ai.config import RiskConfig
from gold_ai.domain import Side, Tick, TradeProposal
from gold_ai.risk.engine import RiskEngine
from gold_ai.timeutil import in_local_window

T0 = datetime(2024, 3, 4, 10, tzinfo=timezone.utc)   # Monday
TICK = Tick(T0, 2400.0, 2400.2)


def prop(**kw):
    d = dict(side=Side.BUY, entry=2400.2, stop_loss=2398.2, take_profit=2403.2, lots=0.05, confidence=0.6,
             valid_until=T0 + timedelta(minutes=1))
    d.update(kw)
    return TradeProposal(**d)


def eng(spec, **cfg):
    e = RiskEngine.create(RiskConfig(**cfg), spec, 10_000)
    e.on_equity(10_000, T0)
    return e


def blocked(v, text):
    return not v.approved and any(text in r for r in v.reasons)


def test_verdict_carries_rule_version_that_changes_with_config(spec):
    a, b = eng(spec), eng(spec, max_trades_per_day=5)
    va = a.evaluate(prop(), TICK, 10_000, 0)
    assert va.approved and va.rule_version.startswith("risk-")
    assert va.rule_version == eng(spec).rule_version() != b.rule_version()


def test_weekly_loss_limit(spec):
    e = eng(spec, max_daily_loss_pct=50)
    e.on_equity(9_800, T0 + timedelta(days=1))          # new day, same week
    assert e.evaluate(prop(), Tick(T0 + timedelta(days=1), 2400, 2400.2), 9_800, 0).approved
    t = T0 + timedelta(days=2)
    e.on_equity(9_590, t)
    assert blocked(e.evaluate(prop(), Tick(t, 2400, 2400.2), 9_590, 0), "weekly loss")
    nxt = T0 + timedelta(days=7)                        # next Monday resets the week
    e.on_equity(9_590, nxt)
    assert e.evaluate(prop(valid_until=nxt + timedelta(minutes=1)), Tick(nxt, 2400, 2400.2), 9_590, 0).approved


def test_consecutive_losses_start_a_cooldown(spec):
    e = eng(spec, max_daily_loss_pct=50, reentry_after_loss_minutes=0)
    for i in range(3):
        e.on_trade_closed(-10, T0 + timedelta(minutes=i))
    now = T0 + timedelta(minutes=30)
    assert blocked(e.evaluate(prop(), Tick(now, 2400, 2400.2), 9_970, 0, now=now), "cooldown after 3 consecutive")
    later = T0 + timedelta(minutes=63)
    assert e.evaluate(prop(), Tick(later, 2400, 2400.2), 9_970, 0, now=later).approved


def test_win_resets_consecutive_losses(spec):
    e = eng(spec, reentry_after_loss_minutes=0)
    e.on_trade_closed(-10, T0)
    e.on_trade_closed(-10, T0)
    e.on_trade_closed(5, T0)
    e.on_trade_closed(-10, T0)
    assert e.state.cooldown_until is None and e.state.consecutive_losses == 1


def test_no_immediate_reentry_after_a_loss(spec):
    e = eng(spec)
    e.on_trade_closed(-10, T0)
    assert blocked(e.evaluate(prop(), TICK, 9_990, 0), "re-entry blocked")
    now = T0 + timedelta(minutes=6)
    assert e.evaluate(prop(), Tick(now, 2400, 2400.2), 9_990, 0, now=now).approved


def test_overtrading_caps(spec):
    e = eng(spec, max_trades_per_day=2)
    e.on_trade_opened(T0 - timedelta(minutes=10))
    e.on_trade_opened(T0 - timedelta(minutes=5))
    assert blocked(e.evaluate(prop(), TICK, 10_000, 0), "overtrading")
    e2 = eng(spec)
    e2.on_trade_opened(T0 - timedelta(minutes=1))
    assert blocked(e2.evaluate(prop(), TICK, 10_000, 0), "min apart")
    e2.on_equity(10_000, T0 + timedelta(days=1))        # counters reset with the day
    assert e2.state.trades_today == 0


def test_abnormal_volatility_spread_and_latency(spec):
    e = eng(spec)
    assert blocked(e.evaluate(prop(), TICK, 10_000, 0, market={"vol_ratio": 4.0}), "abnormal volatility")
    assert blocked(e.evaluate(prop(), TICK, 10_000, 0, market={"spread_z": 6.0}), "abnormal spread")
    assert blocked(e.evaluate(prop(), TICK, 10_000, 0, latency_ms=3000), "latency")
    assert e.evaluate(prop(), TICK, 10_000, 0, market={"vol_ratio": 1.2, "spread_z": 0.5}, latency_ms=80).approved


def test_expected_value_after_costs_gate(spec):
    e = eng(spec)
    assert blocked(e.evaluate(prop(ev_after_cost_r=0.01), TICK, 10_000, 0), "expected value after costs")
    assert e.evaluate(prop(ev_after_cost_r=0.2), TICK, 10_000, 0).approved
    # exploration trades (simulation only, labelled) are not EV-gated; trades without a model are not either
    assert e.evaluate(prop(ev_after_cost_r=-0.5, explanation="x [EXPLORATION]"), TICK, 10_000, 0).approved


def test_observation_window_gates_demo_and_real_not_virtual(spec):
    e = eng(spec)
    e.start("demo", T0 - timedelta(minutes=2))
    assert blocked(e.evaluate(prop(), TICK, 10_000, 0), "observation window")
    e.start("demo", T0 - timedelta(minutes=6))
    assert e.evaluate(prop(), TICK, 10_000, 0).approved
    v = eng(spec)
    v.start("virtual", T0)
    assert v.evaluate(prop(), TICK, 10_000, 0).approved


def test_duplicate_proposal_rejected(spec):
    e = eng(spec)
    p = prop()
    assert e.evaluate(p, TICK, 10_000, 0).approved
    assert e.evaluate(p, TICK, 10_000, 0).approved       # evaluating twice is not an order
    e.on_trade_opened(T0, p)
    assert blocked(e.evaluate(p, TICK, 10_000, 0), "duplicate")


def test_reconciliation_required_after_reconnect(spec):
    e = eng(spec)
    e.on_disconnect()
    assert blocked(e.evaluate(prop(), TICK, 10_000, 0), "connectivity")
    e.on_reconnected(reconciled=False)
    assert blocked(e.evaluate(prop(), TICK, 10_000, 0), "not reconciled")
    e.on_reconnected(reconciled=True)
    assert e.evaluate(prop(), TICK, 10_000, 0).approved


def test_margin_limit(spec):
    from dataclasses import replace
    e = RiskEngine.create(RiskConfig(), replace(spec, margin_initial=2_000.0), 10_000)
    e.on_equity(10_000, T0)
    assert blocked(e.evaluate(prop(), TICK, 10_000, 0, free_margin=200.0), "free margin")
    assert e.evaluate(prop(), TICK, 10_000, 0, free_margin=10_000.0).approved


def test_stop_may_only_tighten(spec):
    e = eng(spec)
    assert not e.validate_stop_change(Side.BUY, 2398.0, 2397.0).approved
    assert e.validate_stop_change(Side.BUY, 2398.0, 2399.0).approved
    assert not e.validate_stop_change(Side.SELL, 2402.0, 2403.0).approved
    assert e.validate_stop_change(Side.SELL, 2402.0, 2401.0).approved


def test_stop_on_wrong_side_rejected(spec):
    assert blocked(eng(spec).evaluate(prop(stop_loss=2401.0), TICK, 10_000, 0), "wrong side")


def test_manual_override_is_recorded_but_never_bypasses(spec):
    e = eng(spec)
    e.trigger_emergency_stop("owner")
    e.record_override("owner", "emergency_stop", "I want this trade", T0)
    assert not e.evaluate(prop(), TICK, 10_000, 0).approved
    assert e.overrides_recent(T0) == 1 and e.state.overrides[0]["applied"] is False


def test_sizing_independent_of_previous_outcomes(spec):
    e = eng(spec, max_daily_loss_pct=100, max_drawdown_pct=100, max_weekly_loss_pct=100)
    base = e.position_size(10_000, 2400.2, 2398.2)
    for i in range(6):
        e.on_trade_closed(-20, T0 + timedelta(minutes=i))
    assert e.position_size(10_000, 2400.2, 2398.2) == base


@pytest.mark.parametrize("hhmm,inside", [("13:59", False), ("14:00", True), ("14:59", True), ("15:00", False)])
def test_dubai_session_window(spec, hhmm, inside):
    h, m = map(int, hhmm.split(":"))
    now = T0.replace(hour=h, minute=m)          # UTC; 14:00 UTC = 18:00 Dubai
    assert in_local_window(now, [("18:00", "19:00")], "Asia/Dubai") is inside
    e = eng(spec, allowed_sessions_local=[("18:00", "19:00")])
    v = e.evaluate(prop(valid_until=now + timedelta(minutes=1)), Tick(now, 2400, 2400.2), 10_000, 0, now=now)
    assert v.approved is inside


def test_local_window_wraps_midnight():
    t = datetime(2024, 3, 4, 20, 30, tzinfo=timezone.utc)   # 00:30 Dubai
    assert in_local_window(t, [("22:00", "02:00")], "Asia/Dubai")
