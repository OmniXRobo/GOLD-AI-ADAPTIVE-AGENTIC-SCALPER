import time
from datetime import datetime, timezone

import pytest

from gold_ai.domain import MemoryDomain, Side, SimTrade, Tick
from gold_ai.memory.store import MemoryStore
from gold_ai.security.auth import CONFIRM_PHRASE, AuthService, TokenSigner

T = datetime(2024, 1, 1, tzinfo=timezone.utc)


def trade(tid, est=True):
    return SimTrade(tid, "mock", "acc", "XAUUSD", Side.BUY, 0.1, T, 2400, 2399, 2402, "s1", "m1",
                    is_estimated_fill=est, exit_time=T, exit_price=2402, net_pnl=19.3, context={"regime": "x"})


def test_domains_are_separate(store):
    store.save_trade(MemoryDomain.HISTORICAL, trade("a"))
    store.save_trade(MemoryDomain.VIRTUAL, trade("b"))
    assert store.count_trades(MemoryDomain.HISTORICAL) == 1
    assert store.count_trades(MemoryDomain.VIRTUAL) == 1
    assert store.count_trades(MemoryDomain.FORWARD) == 0
    t = store.load_trades(MemoryDomain.HISTORICAL)[0]
    assert t.trade_id == "a" and t.entry_time == T and t.context["regime"] == "x"


def test_real_memory_requires_actual_fills(store):
    with pytest.raises(ValueError):
        store.save_trade(MemoryDomain.REAL, trade("r", est=True))
    with pytest.raises(ValueError):
        store.save_trade(MemoryDomain.VIRTUAL, trade("v", est=False))
    store.save_trade(MemoryDomain.REAL, trade("r2", est=False))
    assert store.count_trades(MemoryDomain.REAL) == 1


def test_persistence_survives_reopen(settings):
    s1 = MemoryStore(settings.database_url)
    s1.save_trade(MemoryDomain.FORWARD, trade("p"))
    s1.save_ticks("mock", "XAUUSD", [Tick(T, 1, 1.1)], "synthetic")
    s1.kv_set("k", {"a": 1})
    s2 = MemoryStore(settings.database_url)
    assert s2.count_trades(MemoryDomain.FORWARD) == 1
    assert s2.load_ticks("mock", "XAUUSD")[0].bid == 1
    assert s2.tick_stats()[0]["source"] == "synthetic"
    assert s2.kv_get("k") == {"a": 1}


def test_model_registry_immutable(store):
    assert store.register_model("m1", "s1", {}, {"w": 1})
    assert not store.register_model("m1", "s1", {}, {"w": 2})
    assert store.get_model("m1")["state"] == {"w": 1}
    store.set_model_stage("m1", "validated", "tester")
    assert store.get_model("m1")["stage"] == "validated"
    assert store.audit_log()[0]["action"] == "model_stage"


def test_tokens():
    s = TokenSigner("x" * 32)
    tok = s.sign({"a": 1}, 60)
    assert s.verify(tok)["a"] == 1
    assert s.verify(tok[:-2] + "aa") is None
    assert s.verify(s.sign({"a": 1}, -1)) is None
    with pytest.raises(ValueError):
        TokenSigner("short")


@pytest.fixture
def auth(settings, store):
    settings.account_allowlist = ["111"]
    a = AuthService(settings, store)
    a.create_user("owner", "owner-pass-123", "owner")
    a.create_user("op", "operator-pass-1", "operator")
    return a


def test_login_and_roles(auth):
    assert auth.authenticate("owner", "wrong-password") is None
    u = auth.authenticate("op", "operator-pass-1")
    tok = auth.issue_token(u)
    assert auth.user_from_token(tok).role == "operator"
    from gold_ai.security.auth import Permission
    assert u.has(Permission.BACKTEST) and not u.has(Permission.REAL_EXECUTION)


def test_real_execution_disabled_by_default(auth):
    owner = auth.authenticate("owner", "owner-pass-123")
    auth.grant_real_execution(owner, "owner-pass-123", CONFIRM_PHRASE, ["111"], 0.05, 1)
    ok, why = auth.real_execution_allowed("111", True, 0.01)
    assert not ok and "disabled in configuration" in why


def test_real_execution_grant_flow(auth):
    owner = auth.authenticate("owner", "owner-pass-123")
    op = auth.authenticate("op", "operator-pass-1")
    with pytest.raises(PermissionError):
        auth.grant_real_execution(op, "operator-pass-1", CONFIRM_PHRASE, ["111"], 0.05, 1)
    with pytest.raises(PermissionError):
        auth.grant_real_execution(owner, "owner-pass-123", "yes", ["111"], 0.05, 1)
    with pytest.raises(PermissionError):
        auth.grant_real_execution(owner, "owner-pass-123", CONFIRM_PHRASE, ["999"], 0.05, 1)
    auth.settings.real_trading_enabled = True
    assert not auth.real_execution_allowed("111", True, 0.01)[0]  # no grant yet
    auth.grant_real_execution(owner, "owner-pass-123", CONFIRM_PHRASE, ["111"], 0.05, 1)
    assert auth.real_execution_allowed("111", True, 0.01)[0]
    assert not auth.real_execution_allowed("111", True, 0.5)[0]       # over lot cap
    assert not auth.real_execution_allowed("111", False, 0.01)[0]     # demo account on real path
    auth.set_emergency_stop("owner", True, "test")
    assert not auth.real_execution_allowed("111", True, 0.01)[0]
    auth.set_emergency_stop("owner", False)
    g = auth.store.kv_get("real_execution_grant")
    g["expires"] = time.time() - 1
    auth.store.kv_set("real_execution_grant", g)
    assert "expired" in auth.real_execution_allowed("111", True, 0.01)[1]
    auth.settings.real_trading_enabled = False


def test_approval_tokens_single_use(auth):
    tok = auth.issue_approval("sig1", 30)
    assert not auth.consume_approval(tok, "sig2")
    assert auth.consume_approval(tok, "sig1")
    assert not auth.consume_approval(tok, "sig1")
