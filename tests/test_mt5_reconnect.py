"""The MT5 terminal link can drop (terminal closed, restarted by a live update, hung). The connector must
reconnect on its own and the collector must not flood the log while it is down."""
import logging
import threading
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from gold_ai.brokers.mock_feed import FakeMT5
from gold_ai.brokers.mt5_connector import MT5ReadOnlyConnector
from gold_ai.collector import TickCollector
from gold_ai.domain import Tick

SYMS = [{"name": "XAUUSDm", "currency_base": "XAU", "currency_profit": "USD", "trade_contract_size": 100.0}]


class DroppingMT5(FakeMT5):
    """Fails every call with IPC send failed until initialize() is called again (and `terminal_up`)."""

    def __init__(self):
        super().__init__(SYMS)
        self.broken = False
        self.terminal_up = True
        self.init_calls = []
        self.shutdowns = 0
        self._err = (0, "ok")

    def initialize(self, **kw):
        self.init_calls.append(kw)
        if not self.terminal_up:
            self._err = (-10003, "IPC initialize failed")
            return False
        self.broken = False
        self._err = (0, "ok")
        return True

    def shutdown(self):
        self.shutdowns += 1

    def last_error(self):
        return self._err

    def copy_ticks_range(self, symbol, start, end, flags):
        if self.broken:
            self._err = (-10001, "IPC send failed")
            return None
        return []

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        if self.broken:
            self._err = (-10001, "IPC send failed")
            return None
        return []


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(fake):
    c = MT5ReadOnlyConnector(fake, terminal_path=r"C:\MT5_2\terminal64.exe", server_utc_offset_hours=3)
    c._clock = Clock()
    assert c.connect()
    return c


def test_ipc_failure_reconnects_with_original_arguments():
    fake = DroppingMT5()
    c = make(fake)
    fake.broken = True
    now = datetime.now(timezone.utc)
    try:
        c.ticks_range("XAUUSDm", now - timedelta(minutes=1), now)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "IPC send failed" in str(e)
    assert fake.shutdowns == 1 and len(fake.init_calls) == 2
    assert fake.init_calls[1] == {"path": r"C:\MT5_2\terminal64.exe"}
    assert c.connected and c.reconnects == 1
    assert c.ticks_range("XAUUSDm", now - timedelta(minutes=1), now) == []   # next poll works again
    assert c.link_status()["last_ipc_error_at"] is not None


def test_reconnect_backs_off_while_terminal_is_down():
    fake = DroppingMT5()
    c = make(fake)
    fake.broken, fake.terminal_up = True, False
    for _ in range(20):                      # many workers polling in the same second
        assert c.rates("XAUUSDm", "M1") == []
    assert len(fake.init_calls) == 2          # only one reconnect attempt
    assert not c.connected and c.reconnect_failures == 1
    c._clock.t += 5                           # first retry after 5 s, then 10 s
    c.rates("XAUUSDm", "M1")
    assert len(fake.init_calls) == 3
    c._clock.t += 5
    c.rates("XAUUSDm", "M1")
    assert len(fake.init_calls) == 3
    fake.terminal_up = True                   # owner restarts the terminal
    c._clock.t += 5
    c.rates("XAUUSDm", "M1")
    assert c.connected and c.reconnects == 1
    assert c.rates("XAUUSDm", "M1") == [] and fake.broken is False


def test_non_ipc_error_does_not_reconnect():
    class NoTicks(DroppingMT5):
        def copy_ticks_range(self, symbol, start, end, flags):
            self._err = (-2, "Invalid params")
            return None
    fake = NoTicks()
    c = make(fake)
    now = datetime.now(timezone.utc)
    try:
        c.ticks_range("XAUUSDm", now, now)
    except RuntimeError:
        pass
    assert len(fake.init_calls) == 1 and c.reconnects == 0


class FlakyConn:
    def __init__(self):
        self.fail = True

    def ticks_range(self, symbol, start, end):
        if self.fail:
            raise RuntimeError("copy_ticks_range failed: (-10001, 'IPC send failed')")
        return [Tick(end - timedelta(seconds=1), 2000.0, 2000.2)]


def test_collector_logs_one_traceback_per_outage(store, caplog):
    conn = FlakyConn()
    col = TickCollector(conn, store, "equiti", "XAUUSD.sd", interval_seconds=0)
    stop = threading.Event()
    calls = {"n": 0}
    orig = col.collect_once

    def counted():
        calls["n"] += 1
        if calls["n"] == 50:
            conn.fail = False
        if calls["n"] == 52:
            stop.set()
        return orig()
    col.collect_once = counted
    with caplog.at_level(logging.WARNING, logger="gold_ai.collector"):
        col.run(stop)
    tracebacks = [r for r in caplog.records if r.exc_info]
    assert len(tracebacks) == 1
    assert col.errors == 49 and col.consecutive_errors == 0 and col.failing_since is None
    assert any("resumed after 49" in r.getMessage() for r in caplog.records)
    assert col.status()["last_success_at"] is not None


def test_feed_status_endpoint(settings, store):
    from gold_ai.api.app import AppState, create_app
    st = AppState(settings, store)
    st.auth.create_user("owner", "owner-pass-123", "owner")
    col = TickCollector(FlakyConn(), store, "equiti", "XAUUSD.sd")
    st.collectors["XAUUSD.sd"] = col
    c = TestClient(create_app(st))
    tok = c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert c.get("/api/feed/status").status_code == 401
    assert c.get("/api/feed/status", headers=h).json()["ok"] is True
    for _ in range(3):
        try:
            col.collect_once()
        except RuntimeError as e:
            col._on_error(e)
    r = c.get("/api/feed/status", headers=h).json()
    assert r["ok"] is False and r["down_symbols"] == ["XAUUSD.sd"]
    assert "IPC send failed" in r["last_error"] and r["failing_since"]


class SwitchingMT5(DroppingMT5):
    """A relaunched terminal that comes back on whatever account it saved last."""

    def __init__(self, can_log_back=False):
        super().__init__()
        self.account = (1281361, "EquitiSecurities-Demo")
        self.can_log_back = can_log_back
        self.login_calls = []
        self.selected = []

    def account_info(self):
        login, server = self.account
        return self._Obj(login=login, server=server, currency="USD", trade_mode=0, trade_allowed=True,
                         balance=1.0, equity=1.0, leverage=100, company="x")

    def login(self, login, server=None, **kw):
        self.login_calls.append((login, server))
        if self.can_log_back:
            self.account = (login, server)
            return True
        self._err = (-6, "Terminal: Authorization failed")
        return False

    def symbol_select(self, name, enable):
        self.selected.append(name)
        return True

    def copy_ticks_range(self, symbol, start, end, flags):
        if self.account[0] != 1281361:
            self._err = (-4, "Terminal: Not found")
            return None
        return super().copy_ticks_range(symbol, start, end, flags)


def test_relaunch_on_another_account_stops_reading_and_reports_it():
    fake = SwitchingMT5()
    c = make(fake)
    c.symbol_spec("XAUUSDm", "equiti")
    assert c.expected_account == (1281361, "EquitiSecurities-Demo")
    fake.account = (474869353, "Exness-MT5Trial15")      # terminal relaunched on the saved Exness login
    c._clock.t += 61
    now = datetime.now(timezone.utc)
    try:
        c.ticks_range("XAUUSDm", now - timedelta(minutes=1), now)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "474869353" in str(e) and "expected 1281361" in str(e)
    assert fake.login_calls == [(1281361, "EquitiSecurities-Demo")]   # tried the saved Equiti password
    assert c.link_status()["account_mismatch"] and not c.connected
    assert c.rates("XAUUSDm", "M1") == [] and c.latest_tick("XAUUSDm") is None
    fake.account = (1281361, "EquitiSecurities-Demo")    # owner logs back in
    c._clock.t += 61
    assert c.ticks_range("XAUUSDm", now - timedelta(minutes=1), now) == []
    assert c.account_mismatch is None and fake.selected.count("XAUUSDm") == 2   # symbols re-selected


def test_wrong_account_after_reconnect_logs_back_in_with_saved_password():
    fake = SwitchingMT5(can_log_back=True)
    c = make(fake)
    fake.broken = True
    real_init = fake.initialize

    def relaunch(**kw):
        fake.account = (474869353, "Exness-MT5Trial15")
        return real_init(**kw)
    fake.initialize = relaunch
    c.rates("XAUUSDm", "M1")                             # IPC failure -> reconnect -> wrong account -> login
    assert fake.login_calls == [(1281361, "EquitiSecurities-Demo")]
    assert c.account_mismatch is None and c.connected


def test_feed_status_reports_wrong_account(settings, store):
    from gold_ai.api.app import AppState, create_app
    st = AppState(settings, store)
    st.auth.create_user("owner", "owner-pass-123", "owner")
    fake = SwitchingMT5()
    conn = make(fake)
    st.connectors["equiti"] = conn
    st.collectors["XAUUSD.pr"] = TickCollector(conn, store, "equiti", "XAUUSD.pr")
    fake.account = (474869353, "Exness-MT5Trial15")
    conn._clock.t += 61
    conn.rates("XAUUSD.pr", "M1")
    c = TestClient(create_app(st))
    tok = c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]
    r = c.get("/api/feed/status", headers={"Authorization": f"Bearer {tok}"}).json()
    assert r["ok"] is False and "474869353" in r["account_mismatch"]
