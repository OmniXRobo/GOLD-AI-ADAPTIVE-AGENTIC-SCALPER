"""Strategy Selector Agent: a research lane becomes the champion only on evidence and only by the owner."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from gold_ai.agents import strategy_selector as sel
from gold_ai.api.app import AppState, create_app
from gold_ai.domain import ExitReason, MemoryDomain, Side, SimTrade
from gold_ai.engines.research_lanes import ResearchLaneEngine, lane_params
from gold_ai.security.auth import User
from gold_ai.strategies.agent import RuleParams

CFG = {"setup": "failed_breakout", "risk_reward": 1.5, "tf_scale": "intraday", "trigger_tf": "M5",
       "max_hold_seconds": 8 * 3600}
OWNER, VIEWER = User("owner", "owner"), User("viewer", "viewer")
T0 = datetime.now(timezone.utc) - timedelta(days=20)


class NoQuotes:
    def latest_tick(self, symbol):
        return None


def lane(settings, spec, store):
    return ResearchLaneEngine(settings, spec, NoQuotes(), store, lane_params(CFG))


def research_run(store, spec, verdict="candidate"):
    p = RuleParams(**CFG)                       # research runs use the default style; matching ignores it
    store.save_run(run_id=f"research-{verdict}", domain="historical", kind="research", broker=spec.broker,
                   symbol=spec.symbol, data_source="mt5", data_hash="h", period_start=T0, period_end=T0,
                   strategy_version=p.version(), model_version_start="none", model_version_end="none",
                   params=asdict(p), metrics={"verdict": verdict, "test": {"trades": 40, "expectancy_r": 0.3}})


def forward(store, ln, rs, start):
    for i, r in enumerate(rs):
        t0 = start + timedelta(hours=i)
        store.save_trade(MemoryDomain.VIRTUAL, SimTrade(
            f"f{start.timestamp()}-{i}", ln.spec.broker, "research", ln.spec.symbol, Side.BUY, 0.01, t0, 2400.0,
            2395.0, 2407.5, ln.agent.params.version(), "none", exit_time=t0 + timedelta(minutes=30),
            exit_price=2400.0 + 5 * r, exit_reason=ExitReason.TAKE_PROFIT if r > 0 else ExitReason.STOP_LOSS,
            net_pnl=5.0 * r, initial_risk_money=5.0, context={"style": "research"}))


def test_nothing_is_eligible_without_research_and_forward_evidence(settings, spec, store):
    ln = lane(settings, spec, store)
    ev = sel.evaluate_lane(store, ln, sel.PromotionCriteria())
    assert not ev.eligible and any("no historical research" in r for r in ev.reasons)
    assert any("0 forward trades" in r for r in ev.reasons)
    research_run(store, spec, "insufficient_data")
    forward(store, ln, [1.5, -1.0] * 20, T0)                     # 40 forward trades, but research says no
    ev = sel.evaluate_lane(store, ln, sel.PromotionCriteria())
    assert not ev.eligible and any("research verdict is 'insufficient_data'" in r for r in ev.reasons)
    with pytest.raises(ValueError, match="not eligible"):
        sel.promote(store, ln, sel.PromotionCriteria(), OWNER)


def test_owner_promotes_an_eligible_lane_and_bad_results_demote_it(settings, spec, store):
    ln = lane(settings, spec, store)
    research_run(store, spec, "candidate")
    forward(store, ln, [1.5, 1.5, -1.0] * 12, T0)                  # 36 trades, +0.67R, interval above zero
    crit = sel.PromotionCriteria()
    ev = sel.evaluate_lane(store, ln, crit)
    assert ev.eligible, ev.reasons
    with pytest.raises(PermissionError):
        sel.promote(store, ln, crit, VIEWER)
    sel.promote(store, ln, crit, OWNER)
    assert ln.refresh_champion() and ln.status()["champion"]
    # A restarted lane comes back as champion; its proposals are no longer exploration.
    again = lane(settings, spec, store)
    assert again.agent.champion
    # Clearly negative results after promotion demote it automatically (never the reverse).
    forward(store, again, [-1.0] * 20, datetime.now(timezone.utc) + timedelta(minutes=1))
    assert sel.check_demotion(store, again, crit) is not None
    assert not again.refresh_champion()
    assert [a["action"] for a in store.audit_log() if a["action"].startswith("strategy_")] == [
        "strategy_demoted", "strategy_promoted"]


def test_scoreboard_and_promotion_api(settings, spec, store):
    st = AppState(settings, store)
    ln = lane(settings, spec, store)
    st.research_lanes[ln.key] = ln
    st.auth.create_user("owner", "owner-pass-123", "owner")
    c = TestClient(create_app(st))
    tok = c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    sb = c.get("/api/strategies/scoreboard", headers=h).json()
    assert sb["criteria"]["min_forward_trades"] == 30 and sb["lanes"][0]["eligible"] is False
    r = c.post("/api/strategies/promote", headers=h, json={"lane": ln.key})
    assert r.status_code == 400 and "not eligible" in r.json()["detail"]
    assert c.post("/api/strategies/promote", headers=h, json={"lane": "nope"}).status_code == 404
