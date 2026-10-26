"""Root-cause audit tooling: strategy investigations block promotion/execution/signals, the trade audit
reconciles stored trades, and trades keep the facts the audit needs (initial stop, MFE/MAE, realized payoff)."""
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from gold_ai.agents.decision import ModelState, StrategyParams, TradingDecisionAgent
from gold_ai.agents.self_healing import SelfHealingAgent
from gold_ai.cli import main
from gold_ai.domain import Decision, ExitReason, MemoryDomain, Side, SimTrade, Tick, TradeProposal
from gold_ai.engines.live_virtual import LiveVirtualEngine
from gold_ai.engines.simulator import PositionSimulator
from gold_ai.costs import CostModel
from gold_ai.research.trade_audit import audit_markdown, audit_trades, trade_pips
from gold_ai.security.auth import User
from gold_ai.strategies import investigation as inv

from test_execution import make, proposal

T0 = datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
OWNER = User("owner", "owner")
VIEWER = User("viewer", "viewer")


# -- investigations --------------------------------------------------------------------------------------
def test_seed_opens_the_adaptive_family_once_and_owner_closes_it(store):
    assert inv.seed(store) == [inv.ADAPTIVE_FAMILY]
    assert inv.seed(store) == []
    for v in ("strat-05490a603d", "strat-f85f55f98f", "heal-abc-123456"):
        assert inv.blocking(store, v)["target"] == inv.ADAPTIVE_FAMILY
    assert inv.blocking(store, "rule-breakout-1234abcd") is None
    with pytest.raises(PermissionError):
        inv.close_investigation(store, inv.ADAPTIVE_FAMILY, VIEWER, "no")
    with pytest.raises(ValueError):
        inv.close_investigation(store, inv.ADAPTIVE_FAMILY, OWNER, " ")
    inv.close_investigation(store, inv.ADAPTIVE_FAMILY, OWNER, "fixed and re-validated")
    assert inv.blocking(store, "strat-05490a603d") is None
    assert inv.seed(store) == []          # a closed investigation is not reopened on restart
    actions = [a["action"] for a in store.audit_log()]
    assert "investigation_opened" in actions and "investigation_closed" in actions


def test_exact_version_and_rule_family_flags(store):
    inv.open_investigation(store, "family:rule-breakout", "test", "owner")
    assert inv.blocking(store, "rule-breakout-1234abcd")["target"] == "family:rule-breakout"
    assert inv.blocking(store, "rule-trend_pullback-1234abcd") is None
    inv.open_investigation(store, "rule-trend_pullback-1234abcd", "test", "owner")
    assert inv.blocking(store, "rule-trend_pullback-1234abcd")["target"] == "rule-trend_pullback-1234abcd"


def test_promotion_and_rollback_refused_under_investigation(settings, spec, store):
    inv.seed(store)
    p = StrategyParams(risk_reward=1.4)
    store.register_model("heal-x", p.version(), asdict(p), {}, stage="validated")
    healer = SelfHealingAgent(settings, spec, store)
    with pytest.raises(ValueError, match="under investigation"):
        healer.promote("heal-x", OWNER)
    store.set_model_stage("heal-x", "retired", "test")
    with pytest.raises(ValueError, match="under investigation"):
        healer.rollback("heal-x", OWNER)
    assert store.get_model("heal-x")["stage"] == "retired"


def test_execution_refuses_a_strategy_under_investigation(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, demo_execution_enabled=True)
    inv.seed(store)
    r = ad.execute(proposal(tick), snap, tick, now=tick.time)          # strategy_version "strat-abc"
    assert not r.executed and r.stage == "investigation" and mt5.sent == []


def test_virtual_engine_snapshots_model_and_withholds_signals(settings, spec, store):
    inv.seed(store)

    class Src:
        def latest_tick(self, symbol):
            return None

    eng = LiveVirtualEngine(settings, spec, Src(), store)
    snap = store.get_model(eng.agent.model.version())
    assert snap["stage"] == "under_investigation" and snap["strategy_version"] == eng.agent.params.version()
    assert eng.status()["investigation"]["target"] == inv.ADAPTIVE_FAMILY
    sent = []
    eng.signal_hook = lambda p, t: sent.append(p)
    tick = Tick(T0, 2400.0, 2400.2)
    eng.loop.last_tick = tick
    prop = TradeProposal(Side.BUY, 2400.2, 2397.2, 2404.7, 0.05, 0.7, T0 + timedelta(seconds=60),
                         strategy_version=eng.agent.params.version(), explanation="BUY: model-approved")
    eng._on_decision(Decision(Side.BUY, 0.7, "x", prop, {}), {"approved": True})
    assert sent == []
    inv.close_investigation(store, inv.ADAPTIVE_FAMILY, OWNER, "test")
    eng._on_decision(Decision(Side.BUY, 0.7, "x", prop, {}), {"approved": True})
    assert sent == [prop]
    assert store.register_model(eng.agent.model.version(), "x", {}, {}) is False   # backup is immutable


# -- facts kept on trades ----------------------------------------------------------------------------------
def test_closed_trade_keeps_initial_stop_and_excursions(settings, spec):
    sim = PositionSimulator(CostModel(spec, settings.costs), "b", "a")
    t0 = Tick(T0, 2400.0, 2400.2)
    p = TradeProposal(Side.BUY, 2400.2, 2397.2, 2404.7, 0.1, 0.6, T0 + timedelta(seconds=60),
                      trailing_start=3.0, trailing_distance=2.4)
    sim.open(p, t0, {"style": "scalp"})
    for i, bid in enumerate((2401.0, 2403.6, 2402.0, 2400.9)):
        closed = sim.on_tick(Tick(T0 + timedelta(seconds=i + 1), bid, bid + 0.2))
    t = closed[0]
    assert t.exit_reason == ExitReason.TRAILING_STOP
    assert t.context["initial_stop_loss"] == 2397.2 and t.stop_loss > 2397.2       # final stop was trailed
    assert t.context["trailing_active"] is True
    assert t.context["max_favorable_price"] == pytest.approx(2403.6 - t.entry_price)


def test_expected_value_uses_realized_payoff_not_the_planned_target():
    m = ModelState()
    v0 = m.version()
    assert "payoff" not in m.to_dict()                       # unchanged schema until used: same version id
    assert ModelState.from_dict(m.to_dict()).version() == v0
    agent = TradingDecisionAgent(StrategyParams(), m)
    for _ in range(40):
        agent.learn({}, Side.BUY, True, r=0.2)                # winners closed early by the trailing stop
    pay = m.payoff(Side.BUY)
    assert pay.win_r(1.5) == pytest.approx((10 * 1.5 + 40 * 0.2) / 50)
    assert m.payoff(Side.SELL).win_r(1.5) == 1.5
    again = ModelState.from_dict(json.loads(json.dumps(m.to_dict())))
    assert again.payoff(Side.BUY).win_n == 40 and again.version() == m.version()


# -- trade audit -------------------------------------------------------------------------------------------
def trade(i, side, entry, exit_, *, risk=10.0, net=None, expl="BUY: momentum continuation (m=0.5) [EXPLORATION]",
          reason=ExitReason.STOP_LOSS, minutes=10, start=None, **ctx):
    start = start or T0 + timedelta(hours=i)
    d = 1 if side == Side.BUY else -1
    gross = (exit_ - entry) * d * 100 * 0.01
    return SimTrade(f"t{i}", "equiti", "virtual-1", "XAUUSD.sd", side, 0.01, start, entry,
                    entry - d * 10, entry + d * 15, "strat-f85f55f98f", "model-1",
                    exit_time=start + timedelta(minutes=minutes), exit_price=exit_, exit_reason=reason,
                    gross_pnl=gross, net_pnl=gross if net is None else net, initial_risk_money=risk,
                    spread_cost=0.27, explanation=expl, context={"style": "scalp", "regime": "ranging", **ctx})


def test_audit_headline_matches_dashboard_arithmetic_and_flags_problems():
    ts = [trade(0, Side.BUY, 2400.0, 2390.0), trade(1, Side.SELL, 2400.0, 2391.0, reason=ExitReason.TAKE_PROFIT),
          trade(2, Side.BUY, 2400.0, 2402.0, reason=ExitReason.TRAILING_STOP,
                expl="BUY: rejection near support (0.2 ATR)", exploration=False)]
    rep = audit_trades(ts, domain="virtual")
    h = rep["headline"]
    assert h["trades"] == 3 and h["wins"] == 2 and h["pips_won"] == pytest.approx(110) and h["pips_lost"] == pytest.approx(100)
    assert h["avg_win_pips"] == pytest.approx(55) and h["avg_loss_pips"] == pytest.approx(100)
    assert trade_pips(ts[1]) == pytest.approx(90)
    assert rep["by_exploration"]["exploration"]["trades"] == 2
    assert rep["by_entry_rule"]["rejection_support"]["trades"] == 1
    assert rep["integrity"]["clean"]
    assert rep["exits"]["mfe_mae"]["recorded_trades"] == 0      # older rows did not store excursions
    assert "Trade audit" in audit_markdown(rep)

    bad = ts + [trade(3, Side.BUY, 2400.0, 2390.0, start=ts[0].entry_time),                 # duplicate entry
                trade(4, Side.BUY, 2400.0, 2390.0, start=ts[1].entry_time + timedelta(minutes=5))]  # overlaps t1
    bad[3].trade_id = "dup"
    ig = audit_trades(bad, domain="virtual")["integrity"]
    assert not ig["clean"] and ig["issues"]["duplicate_entries"] and ig["issues"]["overlapping_positions"]


def test_audit_win_rate_test_against_breakeven():
    ts = [trade(i, Side.BUY, 2400.0, 2390.0, net=-10.0) for i in range(23)]
    ts += [trade(23 + i, Side.BUY, 2400.0, 2410.6, net=10.6, reason=ExitReason.TAKE_PROFIT) for i in range(11)]
    r = audit_trades(ts, domain="virtual")["r"]
    assert r["breakeven_win_rate"] == pytest.approx(1 / 2.06, rel=1e-3)
    assert r["observed_win_rate"] == pytest.approx(11 / 34)
    assert 0.0 < r["p_value_win_rate_at_or_below"] < 0.1


def test_audit_cli_is_read_only_and_writes_reports(settings, store, tmp_path, monkeypatch):
    for t in (trade(0, Side.BUY, 2400.0, 2390.0), trade(1, Side.SELL, 2400.0, 2391.0)):
        store.save_trade(MemoryDomain.VIRTUAL, t)
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"database_url": settings.database_url, "data_dir": str(tmp_path),
                               "secret_key": "test-secret-key-0123456789"}))
    assert main(["--config", str(cfg), "audit-trades", "--symbol", "XAUUSD", "--out", str(tmp_path / "a")]) == 0
    files = sorted(p.suffix for p in (tmp_path / "a").iterdir())
    assert files == [".json", ".md"]
    data = json.loads(next((tmp_path / "a").glob("*.json")).read_text())
    assert data["headline"]["trades"] == 2
    assert store.count_trades(MemoryDomain.VIRTUAL) == 2


def test_exit_design_gives_coin_flip_wins_of_about_one_r_on_a_random_walk():
    """Root-cause audit §2.3: with no edge and no costs, the incumbent's exits (stop 1R, trailing from +1R at
    0.8R, target 1.5R) give ~50% wins of ~1R, so a 32% win rate means entries did worse than random."""
    import random

    from gold_ai.brokers.mock_feed import synthetic_spec
    from gold_ai.config import CostConfig

    spec = synthetic_spec(commission=0.0)
    sim = PositionSimulator(CostModel(spec, CostConfig(slippage_points_entry=0, slippage_points_exit=0,
                                                       stop_slippage_extra_points=0)), "b", "a")
    rng, rs, now, px = random.Random(7), [], T0, 2400.0
    for _ in range(1500):
        p = TradeProposal(Side.BUY, px, px - 10.0, px + 15.0, 0.01, 0.5, now + timedelta(days=1),
                          trailing_start=10.0, trailing_distance=8.0)
        sim.open(p, Tick(now, px, px))
        while sim.positions:
            now += timedelta(seconds=1)
            px = round(px + (0.5 if rng.random() < 0.5 else -0.5), 2)
            for t in sim.on_tick(Tick(now, px, px)):
                rs.append(t.r_multiple)
    wins = [r for r in rs if r > 0]
    assert 0.46 < len(wins) / len(rs) < 0.54
    assert 0.9 < sum(wins) / len(wins) < 1.1
    assert abs(sum(rs) / len(rs)) < 0.08
