from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from gold_ai.api.app import AppState, create_app
from gold_ai.domain import ExitReason, MemoryDomain, Side, SimTrade
from gold_ai.notifications import format_profit_alert, profit_alerts

T0 = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)


def trade(tid, pnl, minutes, side=Side.BUY, entry=2400.0, exit_=2402.5, symbol="XAUUSD.sd", real=False,
          closed=True, **ctx):
    return SimTrade(tid, "equiti", "virtual", symbol, side, 0.1, T0, entry, entry - 3, entry + 3, "s1", "m1",
                    is_estimated_fill=not real, exit_time=T0 + timedelta(minutes=minutes) if closed else None,
                    exit_price=exit_ if closed else None, exit_reason=ExitReason.TAKE_PROFIT if closed else None,
                    net_pnl=pnl, initial_risk_money=30.0, context=ctx)


@pytest.fixture
def seeded(store):
    store.save_trade(MemoryDomain.VIRTUAL, trade("win1", 24.0, 5, style="scalp"))
    store.save_trade(MemoryDomain.VIRTUAL, trade("loss1", -12.0, 6))
    store.save_trade(MemoryDomain.VIRTUAL, trade("flat", 0.0, 7))
    store.save_trade(MemoryDomain.VIRTUAL, trade("open", 0.0, 8, closed=False))
    store.save_trade(MemoryDomain.VIRTUAL, trade("win2", 9.5, 20, side=Side.SELL, entry=1.08500, exit_=1.08420,
                                                 symbol="EURUSD", style="swing", exploration=True))
    store.save_trade(MemoryDomain.HISTORICAL, trade("bt", 50.0, 30))
    return store


def test_only_profitable_closes_from_virtual_and_real(seeded):
    a = profit_alerts(seeded)
    assert [x["trade_id"] for x in a] == ["win2", "win1"]      # newest first; losses, flat, open, backtest left out
    w2, w1 = a
    assert w1["account"] == "virtual" and w1["simulated"] is True and w1["pips"] == pytest.approx(25.0)
    assert w2["side"] == "SELL" and w2["pips"] == pytest.approx(8.0) and w2["style_label"] == "Swing"
    assert w2["exploration"] is True and w2["id"] == "virtual:win2"
    assert profit_alerts(seeded, since=T0 + timedelta(minutes=10))[0]["trade_id"] == "win2"
    assert len(profit_alerts(seeded, since=T0 + timedelta(minutes=10))) == 1


def test_real_fills_are_labelled_real(store):
    store.save_trade(MemoryDomain.REAL, trade("r1", 15.0, 3, real=True))
    store.save_trade(MemoryDomain.VIRTUAL, trade("v1", 5.0, 4))
    a = {x["trade_id"]: x for x in profit_alerts(store)}
    assert a["r1"]["simulated"] is False and a["r1"]["account_label"].startswith("Real")
    assert format_profit_alert(a["r1"]).startswith("REAL ")
    assert format_profit_alert(a["v1"]).startswith("VIRTUAL Scalping BUY XAUUSD.sd closed in profit: +5.00")


def test_profit_close_endpoints(settings, seeded):
    st = AppState(settings, seeded)
    st.auth.create_user("viewer", "viewer-pass-12", "viewer")
    c = TestClient(create_app(st))
    assert c.get("/api/alerts/profit-closes").status_code == 401
    tok = c.post("/api/auth/login", json={"username": "viewer", "password": "viewer-pass-12"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    r = c.get("/api/alerts/profit-closes", headers=h)
    assert r.status_code == 200 and [x["trade_id"] for x in r.json()] == ["win2", "win1"]
    r = c.get("/api/alerts/profit-closes", params={"since": (T0 + timedelta(minutes=10)).isoformat()}, headers=h)
    assert [x["trade_id"] for x in r.json()] == ["win2"]
    assert c.get("/api/alerts/profit-closes", params={"since": "soon"}, headers=h).status_code == 422
    # the phone app reads the same list with its read-only device token, and only with it
    assert c.get("/api/device/profit-closes", headers=h).status_code == 401
    dev = c.post("/api/auth/device-token", json={"device": "phone"}, headers=h).json()["token"]
    r = c.get("/api/device/profit-closes", headers={"Authorization": f"Bearer {dev}"})
    assert r.status_code == 200 and len(r.json()) == 2
