from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from gold_ai.brokers.mock_feed import FakeMT5, synthetic_ticks
from gold_ai.brokers.mt5_connector import MT5ReadOnlyConnector
from gold_ai.runtime import build_runtime

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
    app, workers = build_runtime(settings, store, use_mt5=True,
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
