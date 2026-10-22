import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from gold_ai.brokers.mock_feed import FakeMT5, synthetic_ticks
from gold_ai.brokers.mt5_connector import MT5ReadOnlyConnector
from gold_ai.agents.self_healing import SelfHealingAgent
from gold_ai.runtime import build_runtime, scheduled_self_healing

SYMS = [{"name": "XAUUSDm", "currency_base": "XAU", "currency_profit": "USD", "trade_contract_size": 100.0}]


class TickingFake(FakeMT5):
    def __init__(self):
        super().__init__(SYMS)
        start = datetime.now(timezone.utc) - timedelta(hours=3)
        self.stream = iter(synthetic_ticks(20_000, start=start, step_seconds=0.5))

    def symbol_info_tick(self, name):
        t = next(self.stream)
        return self._Obj(time_msc=int(t.time.timestamp() * 1000), bid=t.bid, ask=t.ask, volume_real=1.0)


def test_runtime_with_fake_mt5(settings, store):
    fake = TickingFake()
    app, supervisor = build_runtime(settings, store, use_mt5=True,
                                 connector_factory=lambda: MT5ReadOnlyConnector(fake))
    st = app.state.gold
    st.auth.create_user("owner", "owner-pass-123", "owner")
    eng = next(iter(st.virtual_engines.values()))
    assert eng.spec.symbol == "XAUUSDm" and eng.spec.broker == "exness"
    assert store.kv_get("spec:exness:XAUUSDm")["contract_size"] == 100.0
    for _ in range(12_000):
        eng.poll_once()
    c = TestClient(app)
    tok = c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    ms = c.get("/api/market/state", headers=h).json()
    assert ms["ready"] and ms["symbol"] == "XAUUSDm"
    for path in ("/api/maturity", "/api/maturity?broker=exness", "/api/system/health", "/api/news",
                 "/api/institutional", "/api/signals", "/api/self-healing", "/api/backups", "/api/brokers",
                 "/api/risk", "/api/trades/virtual"):
        r = c.get(path, headers=h)
        assert r.status_code == 200, (path, r.text)
    assert c.get("/api/institutional", headers=h).json()["available"] is False
    m = c.get("/api/maturity?broker=exness", headers=h).json()
    assert m["live_authorized"] is False if "live_authorized" in m else m["stages"]["live_authorized"] is False
    b = c.post("/api/backups", headers=h)
    assert b.status_code == 200, b.text
    assert len(c.get("/api/backups", headers=h).json()) == 1
    assert fake.order_send_calls == 0


def test_virtual_engine_warms_up_from_stored_ticks(settings, store):
    now = datetime.now(timezone.utc)
    stored = synthetic_ticks(12_000, start=now - timedelta(hours=2), step_seconds=0.5)
    store.save_ticks("exness", "XAUUSDm", stored, source="mt5")
    fake = TickingFake()
    app, supervisor = build_runtime(settings, store, use_mt5=True,
                                    connector_factory=lambda: MT5ReadOnlyConnector(fake))
    eng = next(iter(app.state.gold.virtual_engines.values()))
    assert eng.loop.market.state().ready              # no 100-minute wait after a restart
    assert eng.loop.stats.decisions == 0 and eng.loop.stats.ticks == 0   # warm-up never decides or trades
    assert set(supervisor.status()) == {"collector", "live_virtual", "news_sync", "self_healing"}
    supervisor.start()
    try:
        for _ in range(100):
            if supervisor.status()["live_virtual"]["alive"]:
                break
            time.sleep(0.01)
        assert all(w["alive"] for w in supervisor.status().values())
    finally:
        supervisor.stop()
    assert fake.order_send_calls == 0


def test_scheduled_self_healing_runs_once_per_interval(settings, store):
    now = datetime.now(timezone.utc)
    store.save_ticks("exness", "XAUUSDm", synthetic_ticks(2_000, start=now - timedelta(minutes=20),
                                                          step_seconds=0.5), source="mt5")
    fake = TickingFake()
    app, supervisor = build_runtime(settings, store, use_mt5=True,
                                    connector_factory=lambda: MT5ReadOnlyConnector(fake))
    eng = next(iter(app.state.gold.virtual_engines.values()))
    healer = SelfHealingAgent(settings, eng.spec, store)
    entry = scheduled_self_healing(eng, healer, store, error_counters={"collector": 0}, now=now)
    assert entry["outcome"] == "no_action" and entry["registered"] == []
    assert any("insufficient" in d for d in entry["diagnosis"])
    assert scheduled_self_healing(eng, healer, store, now=now + timedelta(hours=1)) is None   # not due yet
    assert scheduled_self_healing(eng, healer, store, now=now + timedelta(hours=25)) is not None
    c = TestClient(app)
    st = app.state.gold
    st.auth.create_user("owner", "owner-pass-123", "owner")
    tok = c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]
    sh = c.get("/api/self-healing", headers={"Authorization": f"Bearer {tok}"}).json()
    assert sh["current_diagnosis"]["cycle_id"] == sh["history"][-1]["cycle_id"]
    assert fake.order_send_calls == 0


def test_ws_tokens_redacted_in_logs():
    import logging
    from gold_ai.cli import RedactTokens
    rec = logging.LogRecord("uvicorn.error", logging.INFO, "", 0, '%s - "WebSocket %s" [accepted]',
                            ("127.0.0.1:5", "/ws/live?token=eyJabc.def&x=1"), None)
    RedactTokens().filter(rec)
    assert "eyJabc" not in rec.getMessage() and "token=REDACTED&x=1" in rec.getMessage()
