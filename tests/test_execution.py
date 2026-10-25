"""Execution adapter tests. Only a fake MT5 module is used — no broker is ever contacted."""
import time
from datetime import timedelta

import pytest

from gold_ai.brokers.mt5_connector import AccountSnapshot
from gold_ai.config import Settings
from gold_ai.domain import MemoryDomain, Side, Tick, TradeProposal, utcnow
from gold_ai.execution import DEFAULT_MAGIC, DEMO_LOG_KEY, MT5ExecutionAdapter
from gold_ai.memory.store import MemoryStore
from gold_ai.risk.engine import RiskEngine
from gold_ai.security.auth import AuthService

LOGIN = "12345"


class O:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeTradeMT5:
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_DONE = 10009
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1

    def __init__(self, trade_mode=0, stops_level=20, filling_mode=2, tick=None):
        self.trade_mode = trade_mode
        self.stops_level = stops_level
        self.filling_mode = filling_mode
        self.positions: list[O] = []
        self.sent: list[dict] = []
        self.tick = tick
        self._next = 5000

    def last_error(self):
        return (0, "ok")

    def account_info(self):
        return O(login=int(LOGIN), trade_mode=self.trade_mode, trade_allowed=True)

    def symbol_info(self, name):
        return O(name=name, digits=2, point=0.01, volume_min=0.01, volume_max=100.0, volume_step=0.01,
                 trade_stops_level=self.stops_level, trade_freeze_level=0, filling_mode=self.filling_mode,
                 trade_exemode=2, trade_mode=4)

    def symbol_info_tick(self, name):
        return O(bid=self.tick.bid, ask=self.tick.ask, time_msc=0)

    def positions_get(self, symbol=None, ticket=None):
        if ticket is not None:
            return [p for p in self.positions if p.ticket == ticket]
        return [p for p in self.positions if symbol is None or p.symbol == symbol]

    def order_check(self, request):
        return O(retcode=0, comment="Done")

    def order_send(self, request):
        self.sent.append(dict(request))
        if request["action"] == self.TRADE_ACTION_DEAL and "position" not in request:
            self._next += 1
            self.positions.append(O(ticket=self._next, symbol=request["symbol"], type=request["type"],
                                    volume=request["volume"], price_open=request["price"], sl=request["sl"],
                                    tp=request["tp"], magic=request["magic"]))
            return O(retcode=10009, order=self._next, deal=self._next + 100000, price=request["price"] + 0.02,
                     volume=request["volume"], comment="Request executed")
        if request["action"] == self.TRADE_ACTION_DEAL:
            self.positions = [p for p in self.positions if p.ticket != request["position"]]
            return O(retcode=10009, order=1, deal=2, price=request["price"], volume=request["volume"], comment="ok")
        for p in self.positions:
            if p.ticket == request["position"]:
                p.sl = request["sl"]
        return O(retcode=10009, comment="ok")


def make(tmp_path, *, trade_mode=0, mode="demo", fake_kw=None, **settings_kw):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/x.db", secret_key="test-secret-key-0123456789",
                        **settings_kw)
    store = MemoryStore(settings.database_url)
    auth = AuthService(settings, store)
    from gold_ai.brokers.mock_feed import synthetic_spec
    spec = synthetic_spec()
    risk = RiskEngine.create(settings.risk, spec, 10_000.0)
    now = utcnow()
    tick = Tick(now, 2400.00, 2400.20)
    mt5 = FakeTradeMT5(trade_mode=trade_mode, tick=tick, **(fake_kw or {}))
    adapter = MT5ExecutionAdapter(mt5, auth, risk, store, mode=mode)
    risk.start(mode, now - timedelta(minutes=10))   # start-up observation window already elapsed
    snap = AccountSnapshot("exness", "Exness-MT5Trial", LOGIN, "USD",
                           {0: "demo", 2: "real"}[trade_mode], True, 10_000.0, 10_000.0, 500)
    return adapter, mt5, store, auth, snap, tick


def proposal(tick, side=Side.BUY, sl_d=3.0, rr=1.5, lots=0.05):
    entry = tick.ask if side == Side.BUY else tick.bid
    sgn = 1 if side == Side.BUY else -1
    return TradeProposal(side, entry, entry - sgn * sl_d, entry + sgn * sl_d * rr, lots, 0.7,
                         tick.time + timedelta(seconds=60), strategy_version="strat-abc", model_version="model-1",
                         explanation="test")


def grant(store, accounts=(LOGIN,), max_lots=1.0):
    store.kv_set("real_execution_grant", {"accounts": list(accounts), "max_lots": max_lots,
                                          "expires": time.time() + 3600, "granted_by": "owner"})


def test_real_execution_refused_by_default_config(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, trade_mode=2, mode="real", account_allowlist=[LOGIN])
    grant(store)
    r = ad.execute(proposal(tick), snap, tick, now=tick.time)
    assert not r.executed and r.stage == "authorization" and "disabled in configuration" in r.reasons[0]
    assert mt5.sent == []
    assert store.count_trades(MemoryDomain.REAL) == 0


def test_real_refused_without_grant(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, trade_mode=2, mode="real", real_trading_enabled=True,
                                         account_allowlist=[LOGIN])
    r = ad.execute(proposal(tick), snap, tick, now=tick.time)
    assert not r.executed and r.reasons == ["no owner authorization grant"] and mt5.sent == []


def test_real_refused_for_non_allowlisted_account(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, trade_mode=2, mode="real", real_trading_enabled=True,
                                         account_allowlist=["999"])
    grant(store)  # even a grant naming the account cannot bypass the allowlist
    r = ad.execute(proposal(tick), snap, tick, now=tick.time)
    assert not r.executed and r.reasons == ["account not in allowlist"] and mt5.sent == []


def test_real_path_refuses_demo_account(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, trade_mode=0, mode="real", real_trading_enabled=True,
                                         account_allowlist=[LOGIN])
    grant(store)
    r = ad.execute(proposal(tick), snap, tick, now=tick.time)
    assert not r.executed and "not a real account" in r.reasons[0] and mt5.sent == []


def test_demo_path_refuses_real_account(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, trade_mode=2, mode="demo", demo_execution_enabled=True)
    r = ad.execute(proposal(tick), snap, tick, now=tick.time)
    assert not r.executed and r.stage == "authorization" and "refuses real accounts" in r.reasons[0]
    assert mt5.sent == []


def test_demo_disabled_by_default(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path)
    r =ad.execute(proposal(tick), snap, tick, now=tick.time)
    assert not r.executed and "disabled in configuration" in r.reasons[0] and mt5.sent == []


@pytest.mark.parametrize("gate,stage", [("emergency_kv", "emergency_stop"), ("emergency_risk", "emergency_stop"),
                                        ("snapshot_mismatch", "account"), ("risk_rr", "risk"),
                                        ("risk_stale", "risk"), ("stop_level", "broker_validation"),
                                        ("filling", "broker_validation"), ("max_positions", "risk")])
def test_order_send_never_called_when_a_gate_fails(tmp_path, gate, stage):
    fake_kw = {}
    if gate == "stop_level":
        fake_kw["stops_level"] = 500
    if gate == "filling":
        fake_kw["filling_mode"] = 0
    ad, mt5, store, auth, snap, tick = make(tmp_path, demo_execution_enabled=True, fake_kw=fake_kw)
    p = proposal(tick)
    now = tick.time
    if gate == "emergency_kv":
        auth.set_emergency_stop("owner", True, "test")
    elif gate == "emergency_risk":
        ad.risk.trigger_emergency_stop("drawdown")
    elif gate == "snapshot_mismatch":
        snap.trade_mode = "real"           # snapshot disagrees with the live terminal
    elif gate == "risk_rr":
        p = proposal(tick, rr=0.5)
    elif gate == "risk_stale":
        now = tick.time + timedelta(minutes=5)
    elif gate == "max_positions":
        mt5.positions.append(O(ticket=1, symbol="XAUUSD", type=0, volume=0.1, sl=0, tp=0, magic=1))
    r = ad.execute(p, snap, tick, now=now)
    assert not r.executed and r.stage == stage, r
    assert mt5.sent == []
    assert store.kv_get(DEMO_LOG_KEY) is None
    assert any(a["action"] == "execution_refused" for a in store.audit_log())


def test_demo_order_with_all_gates_open_sends_exactly_once(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, demo_execution_enabled=True)
    p = proposal(tick, lots=0.05)
    r = ad.execute(p, snap, tick, now=tick.time)
    assert r.executed and r.stage == "sent" and r.account_mode == "demo"
    assert len(mt5.sent) == 1
    req = mt5.sent[0]
    assert req["action"] == FakeTradeMT5.TRADE_ACTION_DEAL
    assert req["type"] == FakeTradeMT5.ORDER_TYPE_BUY
    assert req["symbol"] == "XAUUSD" and req["volume"] == pytest.approx(0.05)
    assert req["price"] == pytest.approx(tick.ask)
    assert req["sl"] == pytest.approx(round(p.stop_loss, 2)) and req["tp"] == pytest.approx(round(p.take_profit, 2))
    assert req["deviation"] == ad.risk.cfg.max_slippage_points
    assert req["type_filling"] == FakeTradeMT5.ORDER_FILLING_IOC
    assert req["magic"] == DEFAULT_MAGIC and req["comment"].startswith("goldai") and len(req["comment"]) <= 31
    # demo fills never reach Memory D
    assert store.count_trades(MemoryDomain.REAL) == 0
    log = store.kv_get(DEMO_LOG_KEY)
    assert len(log) == 1 and log[0]["status"] == "open" and log[0]["price"] == pytest.approx(tick.ask + 0.02)
    assert r.trade.is_estimated_fill is False


def test_sell_uses_bid_and_risk_resizes(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, demo_execution_enabled=True)
    r = ad.execute(proposal(tick, side=Side.SELL, lots=5.0), snap, tick, now=tick.time)
    assert r.executed
    req = mt5.sent[0]
    assert req["type"] == FakeTradeMT5.ORDER_TYPE_SELL and req["price"] == pytest.approx(tick.bid)
    assert req["volume"] <= ad.risk.cfg.max_lots_per_trade  # fresh risk evaluation capped the size


def test_real_fill_recorded_in_memory_d_when_every_gate_open(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, trade_mode=2, mode="real", real_trading_enabled=True,
                                         account_allowlist=[LOGIN])
    grant(store, max_lots=0.1)
    r = ad.execute(proposal(tick, lots=0.05), snap, tick, now=tick.time)
    assert r.executed and len(mt5.sent) == 1
    real = store.load_trades(MemoryDomain.REAL)
    assert len(real) == 1 and real[0].is_estimated_fill is False
    assert real[0].entry_price == pytest.approx(tick.ask + 0.02)       # actual fill, not the quote
    assert store.kv_get(DEMO_LOG_KEY) is None
    # reconciliation after a "restart": broker and store agree
    rep = MT5ExecutionAdapter(mt5, ad.auth, ad.risk, store, mode="real").reconcile()
    assert rep.clean and rep.matched == [real[0].context["position_ticket"]]


def test_real_lots_above_grant_refused(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, trade_mode=2, mode="real", real_trading_enabled=True,
                                         account_allowlist=[LOGIN])
    grant(store, max_lots=0.01)
    r = ad.execute(proposal(tick, lots=0.05), snap, tick, now=tick.time)
    assert not r.executed and "exceed granted maximum" in r.reasons[0] and mt5.sent == []


def test_reconcile_reports_orphans_missing_and_foreign(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, demo_execution_enabled=True)
    assert ad.execute(proposal(tick), snap, tick, now=tick.time).executed
    ours = mt5.positions[0].ticket
    mt5.positions.append(O(ticket=777, symbol="XAUUSD", type=0, volume=0.1, sl=0, tp=0, magic=DEFAULT_MAGIC))
    mt5.positions.append(O(ticket=888, symbol="XAUUSD", type=1, volume=0.1, sl=0, tp=0, magic=42))
    rep = ad.reconcile()
    assert rep.matched == [ours] and [o["ticket"] for o in rep.orphans] == [777]
    assert [f["ticket"] for f in rep.foreign] == [888] and not rep.missing
    mt5.positions = [p for p in mt5.positions if p.ticket != ours]
    rep = ad.reconcile()
    assert [m["ticket"] for m in rep.missing] == [ours] and not rep.clean


def test_emergency_close_all(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, demo_execution_enabled=True)
    assert ad.execute(proposal(tick), snap, tick, now=tick.time).executed
    mt5.positions.append(O(ticket=888, symbol="XAUUSD", type=1, volume=0.1, sl=0, tp=0, magic=42))
    res = ad.emergency_close_all("owner", "panic")
    assert len(res) == 1 and res[0]["closed"]
    close_req = mt5.sent[-1]
    assert close_req["type"] == FakeTradeMT5.ORDER_TYPE_SELL and close_req["position"] == res[0]["ticket"]
    assert [p.ticket for p in mt5.positions] == [888]           # foreign position untouched
    assert store.kv_get("emergency_stop") is True
    assert ad.reconcile().clean
    n = len(mt5.sent)
    assert not ad.execute(proposal(tick), snap, tick, now=tick.time).executed
    assert len(mt5.sent) == n


def test_trailing_stop_only_tightens(tmp_path):
    ad, mt5, store, _, snap, tick = make(tmp_path, demo_execution_enabled=True)
    assert ad.execute(proposal(tick), snap, tick, now=tick.time).executed
    pos = mt5.positions[0]
    n = len(mt5.sent)
    assert not ad.modify_trailing_stop(pos.ticket, pos.sl - 1.0, tick).executed     # loosening refused
    assert not ad.modify_trailing_stop(pos.ticket, tick.bid - 0.05, tick).executed  # inside stop level
    assert len(mt5.sent) == n
    r = ad.modify_trailing_stop(pos.ticket, pos.sl + 1.0, tick)
    assert r.executed and r.request["action"] == FakeTradeMT5.TRADE_ACTION_SLTP
    assert r.request["position"] == pos.ticket and r.request["tp"] == pytest.approx(pos.tp)
    assert mt5.positions[0].sl == pytest.approx(r.request["sl"])


def test_no_order_during_startup_observation_window(tmp_path):
    adapter, mt5, store, auth, snap, tick = make(tmp_path, demo_execution_enabled=True)
    adapter.risk.start("demo", tick.time)          # just started: observation only
    res = adapter.execute(proposal(tick), snap, tick, now=tick.time)
    assert not res.executed and res.stage == "risk"
    assert any("observation window" in r for r in res.reasons)
    assert mt5.sent == []
