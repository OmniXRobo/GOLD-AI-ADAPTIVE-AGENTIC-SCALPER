import pytest
from fastapi.testclient import TestClient

from gold_ai.api.app import AppState, create_app
from gold_ai.domain import MemoryDomain


@pytest.fixture
def client(settings, store):
    st = AppState(settings, store)
    st.auth.create_user("owner", "owner-pass-123", "owner")
    st.auth.create_user("viewer", "viewer-pass-12", "viewer")
    return TestClient(create_app(st)), st


def login(c, u, p):
    r = c.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_requires_auth(client):
    c, _ = client
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/overview").status_code == 401
    assert c.post("/api/auth/login", json={"username": "owner", "password": "nope-nope-1"}).status_code == 401


def test_overview_and_defaults(client):
    c, _ = client
    h = login(c, "owner", "owner-pass-123")
    o = c.get("/api/overview", headers=h).json()
    assert o["real_trading_enabled"] is False
    assert o["memory_counts"] == {"historical": 0, "forward": 0, "virtual": 0, "real": 0}
    a = c.get("/api/authorization", headers=h).json()
    assert a["grant"] is None and a["real_trading_enabled"] is False
    s = c.get("/api/settings", headers=h).json()
    assert s["secret_key"] == "***"


def test_synthetic_backtest_is_labeled_and_stored(client):
    c, st = client
    h = login(c, "owner", "owner-pass-123")
    r = c.post("/api/backtest", headers=h, json={"source": "synthetic", "synthetic_ticks": 20000,
                                                 "params": {"exploration_rate": 0.5, "min_samples": 10**9}})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["data_source"] == "synthetic" and "synthetic random data" in j["synthetic_warning"]
    t = c.get("/api/trades/historical", headers=h).json()
    assert t["simulated"] is True and t["label"].startswith("SIMULATED")
    assert t["metrics"]["total_trades"] == j["metrics"]["total_trades"] == st.store.count_trades(
        MemoryDomain.HISTORICAL)
    assert c.get("/api/trades/real", headers=h).json()["label"] == "ACTUAL BROKER FILLS"
    assert c.get("/api/runs?domain=historical", headers=h).json()[0]["data_source"] == "synthetic"


def test_db_backtest_without_data_is_refused(client):
    c, _ = client
    h = login(c, "owner", "owner-pass-123")
    r = c.post("/api/backtest", headers=h, json={"source": "db", "broker": "exness", "symbol": "XAUUSDm"})
    assert r.status_code == 400


def test_viewer_cannot_mutate(client):
    c, _ = client
    h = login(c, "viewer", "viewer-pass-12")
    assert c.post("/api/backtest", headers=h, json={"source": "synthetic"}).status_code == 403
    assert c.post("/api/emergency-stop", headers=h, json={"active": True}).status_code == 403
    assert c.post("/api/authorization/grant", headers=h, json={"password": "x", "phrase": "x", "accounts": ["1"],
                                                               "max_lots": 1, "hours": 1}).status_code == 403


def test_emergency_stop_and_grant_refusal(client):
    c, st = client
    h = login(c, "owner", "owner-pass-123")
    assert c.post("/api/emergency-stop", headers=h, json={"active": True, "reason": "t"}).json()["emergency_stop"]
    assert c.get("/api/overview", headers=h).json()["emergency_stop"] is True
    r = c.post("/api/authorization/grant", headers=h, json={"password": "owner-pass-123", "phrase": "wrong",
                                                            "accounts": ["1"], "max_lots": 0.1, "hours": 1})
    assert r.status_code == 403
    acts = [a["action"] for a in c.get("/api/audit", headers=h).json()]
    assert "emergency_stop" in acts


def test_unconfigured_optional_service(client):
    c, _ = client
    h = login(c, "owner", "owner-pass-123")
    assert c.get("/api/news", headers=h).status_code == 503


def test_websocket_requires_token(client):
    c, _ = client
    h = login(c, "owner", "owner-pass-123")
    tok = h["Authorization"].split()[1]
    with c.websocket_connect(f"/ws/live?token={tok}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "status" and msg["real_trading_enabled"] is False


def test_websocket_reads_database_off_the_event_loop(client):
    # A slow database read on the event loop froze every page and script the server sends (app stuck loading).
    import asyncio
    c, st = client
    on_loop = []
    orig = st.store.count_trades

    def count(*a, **k):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return orig(*a, **k)

    st.store.count_trades = count
    tok = login(c, "owner", "owner-pass-123")["Authorization"].split()[1]
    with c.websocket_connect(f"/ws/live?token={tok}") as ws:
        ws.receive_json()
    assert on_loop and not any(on_loop)


def test_device_token_is_read_only_and_revocable(client):
    c, st = client
    st.extras["signals"] = lambda: [{"id": "s1", "status": "pending", "action_token": "secret-action"}]
    h = login(c, "viewer", "viewer-pass-12")
    assert c.post("/api/auth/device-token", json={"device": "phone"}).status_code == 401
    r = c.post("/api/auth/device-token", json={"device": "phone"}, headers=h).json()
    assert r["scope"] == "signals:read"
    d = {"Authorization": f"Bearer {r['token']}"}
    sig = c.get("/api/device/signals", headers=d)
    assert sig.status_code == 200
    assert sig.json() == [{"id": "s1", "status": "pending"}]  # action token never leaves the session API
    # a device token is not a session token
    assert c.get("/api/overview", headers=d).status_code == 401
    assert c.get("/api/device/signals", headers=h).status_code == 401
    # only an admin may revoke; revoking invalidates every device token
    assert c.post("/api/auth/device-token/revoke-all", headers=h).status_code == 403
    ho = login(c, "owner", "owner-pass-123")
    assert c.post("/api/auth/device-token/revoke-all", headers=ho).status_code == 200
    assert c.get("/api/device/signals", headers=d).status_code == 401


def test_signal_action_reads_json_body(client):
    c, st = client
    seen = {}

    def act(signal_id, action, token, user):
        seen.update(id=signal_id, action=action, token=token, user=user.username)
        return {"ok": True}

    st.extras["signal_action"] = act
    h = login(c, "owner", "owner-pass-123")
    r = c.post("/api/signals/abc/action", json={"action": "reject", "token": "t1"}, headers=h)
    assert r.status_code == 200
    assert seen == {"id": "abc", "action": "reject", "token": "t1", "user": "owner"}


def test_dashboard_static_files_stay_inside_build_folder(settings, store, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("do not serve")
    c = TestClient(create_app(AppState(settings, store), dashboard_dir=dist))
    assert c.get("/favicon.svg").text == "<svg/>"
    assert c.get("/signals").text == "<html>app</html>"
    # index.html names the current build's scripts, so it must never be served from a stale cache
    assert c.get("/signals").headers["cache-control"] == "no-cache"
    assert c.get("/index.html").headers["cache-control"] == "no-cache"
    assert "do not serve" not in c.get("/..%2Fsecret.txt").text
