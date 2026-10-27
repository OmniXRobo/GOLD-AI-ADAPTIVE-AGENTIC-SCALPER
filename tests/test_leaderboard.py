from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from gold_ai.agents.leaderboard import agent_name, leaderboard
from gold_ai.api.app import AppState, create_app
from gold_ai.domain import ExitReason, MemoryDomain, Side, SimTrade

T0 = datetime(2026, 10, 20, 8, tzinfo=timezone.utc)


def trade(i, pnl, style="scalp", version="dp-abc", model="model-1", symbol="XAUUSD.sd"):
    return SimTrade(f"t{i}", "equiti", "demo", symbol, Side.BUY, 0.01, T0 + timedelta(hours=i), 4000.0, 3998.0,
                    4004.0, version, model, exit_time=T0 + timedelta(hours=i, minutes=30), exit_price=4001.0,
                    exit_reason=ExitReason.TAKE_PROFIT if pnl > 0 else ExitReason.STOP_LOSS, net_pnl=pnl,
                    initial_risk_money=2.0, context={"style": style})


def test_names():
    assert agent_name("scalp", "dp-1") == "Adaptive AI agent · Scalp"
    assert agent_name("research", "rule-failed_breakout-1a2b3c4d") == "Research lane · failed breakout"


def test_totals_per_agent_and_version():
    ts = [trade(0, 4.0), trade(1, -2.0), trade(2, 3.0, model="model-2"),
          trade(3, -1.0, style="swing", version="dp-swing"),
          trade(4, 2.0, style="research", version="rule-trend_pullback-0011aabb", model="none")]
    rows = {r["agent"]: r for r in leaderboard(ts)}
    s = rows["Adaptive AI agent · Scalp"]
    assert (s["trades"], s["wins"], s["losses"]) == (3, 2, 1)
    assert abs(s["net_profit"] - 5.0) < 1e-9 and abs(s["profit_factor"] - 3.5) < 1e-9
    assert abs(s["win_rate"] - 2 / 3) < 1e-9 and s["max_drawdown"] == 2.0
    assert s["version"] == "dp-abc" and s["model_version"] == "model-2" and s["symbols"] == ["XAUUSD.sd"]
    r = rows["Research lane · trend pullback"]
    assert r["profit_factor"] is None and r["no_losses"] and r["model_version"] is None
    assert rows["Adaptive AI agent · Swing"]["net_profit"] == -1.0


def test_running_agent_without_trades_is_listed_with_zero():
    rows = leaderboard([], engines=[{"style": "scalp", "strategy_version": "dp-x", "model_version": "model-9",
                                     "broker": "equiti", "symbol": "XAUUSD.sd"}],
                       lanes=[{"strategy_version": "rule-breakout-12345678", "broker": "equiti",
                               "symbol": "XAUUSD.sd", "champion": True}])
    assert [(r["agent"], r["trades"], r["running"]) for r in rows] == [
        ("Adaptive AI agent · Scalp", 0, True), ("Research lane · breakout", 0, True)]
    assert rows[1]["champion"] and rows[0]["model_version"] == "model-9"


def test_endpoint(settings, store):
    for t in (trade(0, 4.0), trade(1, -2.0)):
        store.save_trade(MemoryDomain.VIRTUAL, t)
    st = AppState(settings, store)
    st.auth.create_user("owner", "owner-pass-123", "owner")
    c = TestClient(create_app(st))
    tok = c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert c.get("/api/agents/leaderboard").status_code == 401
    r = c.get("/api/agents/leaderboard", headers=h).json()
    assert r["simulated"] is True and r["agents"][0]["trades"] == 2
    real = c.get("/api/agents/leaderboard?domain=real", headers=h).json()
    assert real["simulated"] is False and real["agents"] == []
    assert c.get("/api/agents/leaderboard?domain=historical", headers=h).status_code == 422
