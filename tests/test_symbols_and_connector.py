import time
from datetime import datetime, timedelta, timezone

import pytest

from gold_ai.brokers.mock_feed import FakeMT5
from gold_ai.brokers.mt5_connector import MT5ReadOnlyConnector, identify_broker
from gold_ai.brokers.symbols import discover_gold_symbols, evaluate_symbol
from gold_ai.domain import Tick

SYMS = [
    {"name": "XAUUSDm", "currency_base": "XAU", "currency_profit": "USD", "trade_contract_size": 100.0},
    {"name": "XAUUSD.a", "currency_base": "XAU", "currency_profit": "USD", "trade_contract_size": 100.0},
    {"name": "GOLD", "currency_base": "XAU", "currency_profit": "USD", "trade_contract_size": 100.0},
    {"name": "XAUEUR", "currency_base": "XAU", "currency_profit": "EUR", "trade_contract_size": 100.0},
    {"name": "XAUUSD_FUT", "currency_base": "XAU", "currency_profit": "USD"},
    {"name": "EURUSD", "currency_base": "EUR", "currency_profit": "USD", "trade_contract_size": 100000.0},
    {"name": "GOLDX", "currency_base": "", "currency_profit": "USD", "description": "Gold vs US Dollar",
     "trade_contract_size": 100.0},
]


def test_discovery_accepts_aliases_and_rejects_others():
    names = [c.name for c in discover_gold_symbols(SYMS)]
    assert "XAUUSDm" in names and "XAUUSD.a" in names and "GOLD" in names
    assert "XAUEUR" not in names and "EURUSD" not in names and "XAUUSD_FUT" not in names


def test_name_alone_is_not_enough():
    c = evaluate_symbol({"name": "XAUUSD", "currency_base": "EUR", "currency_profit": "USD"})
    assert c.rejected


def test_identify_broker():
    assert identify_broker("Exness-MT5Real8") == "exness"
    assert identify_broker("Equiti-Live") == "equiti"
    assert identify_broker("MEXAtlantic-Real") == "multibank"
    assert identify_broker("SomeBroker-Demo") == "generic"


def test_connector_reads_specs_and_ticks():
    t = Tick(datetime(2024, 5, 1, 10, tzinfo=timezone.utc), 2300.10, 2300.30)
    fake = FakeMT5(SYMS, {"XAUUSDm": t})
    c = MT5ReadOnlyConnector(fake, server_utc_offset_hours=0)
    assert c.connect()
    acct = c.account()
    assert acct.broker == "exness" and acct.trade_mode == "demo" and not acct.is_real
    assert c.discover_gold()[0] in ("GOLD", "XAUUSDm")
    spec = c.symbol_spec("XAUUSDm", acct.broker)
    assert spec.contract_size == 100.0 and spec.swap_mode == "points" and "FOK" in spec.filling_modes
    tick = c.latest_tick("XAUUSDm")
    assert tick.bid == 2300.10 and tick.time == t.time
    assert c.health()["connected"]


def test_connector_has_no_order_api():
    c = MT5ReadOnlyConnector(FakeMT5(SYMS))
    for name in ("order_send", "send_order", "buy", "sell", "close_position"):
        assert not hasattr(c, name)


def test_real_account_detection():
    c = MT5ReadOnlyConnector(FakeMT5(SYMS, trade_mode=2))
    assert c.account().is_real


def test_volume_rounding(spec):
    assert spec.round_volume(0.016) == 0.01
    assert spec.round_volume(0.005) == 0.0
    assert spec.round_volume(500) == spec.volume_max


class ServerTimeFake(FakeMT5):
    """Ticks stamped in broker server time (UTC+3), like MetaQuotes-Demo in summer."""

    def __init__(self, offset_hours=3.0, age_seconds=0.0):
        super().__init__(SYMS)
        self.offset = offset_hours * 3600
        self.age = age_seconds
        self.n = 0
        self.ranges = []

    def symbol_info_tick(self, name):
        self.n += 1
        raw = time.time() - self.age + self.offset
        return self._Obj(time_msc=int(raw * 1000) + self.n, bid=2300.0, ask=2300.3, volume_real=0.0)

    def copy_ticks_range(self, symbol, start, end, flags):
        self.ranges.append((start, end))
        return None


def test_server_offset_detected_from_live_ticks():
    c = MT5ReadOnlyConnector(ServerTimeFake(3.0))
    assert c.latest_tick("XAUUSDm") is None          # first sighting: cannot tell fresh from stale
    t = c.latest_tick("XAUUSDm")
    assert c.server_time_info() == {"offset_hours": 3.0, "pinned": False}
    assert abs((datetime.now(timezone.utc) - t.time).total_seconds()) < 5


def test_stale_quote_never_sets_offset():
    fake = ServerTimeFake(3.0, age_seconds=2 * 86400 + 777)   # weekend: last quote is days old
    c = MT5ReadOnlyConnector(fake)
    for _ in range(3):
        assert c.latest_tick("XAUUSDm") is None
    assert not c.server_offset_known
    with pytest.raises(RuntimeError):
        c.ticks_range("XAUUSDm", datetime.now(timezone.utc), datetime.now(timezone.utc))


def test_ticks_range_requests_server_time():
    fake = ServerTimeFake(0.0)
    c = MT5ReadOnlyConnector(fake, server_utc_offset_hours=3)
    start = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError):   # fake returns None -> copy failed
        c.ticks_range("XAUUSDm", start, start + timedelta(minutes=5))
    assert fake.ranges[0][0] == start + timedelta(hours=3)


def test_offset_locked_mid_session_remeasured_after_pause():
    c = MT5ReadOnlyConnector(FakeMT5(SYMS))
    t0 = 1_800_000_000.0
    c._observe_offset("X", int((t0 + 3 * 3600) * 1000), now=t0)
    c._observe_offset("X", int((t0 + 1 + 3 * 3600) * 1000), now=t0 + 1)
    assert c.server_offset_s == 3 * 3600
    c._observe_offset("X", int((t0 + 2 + 2 * 3600) * 1000), now=t0 + 2)   # mid-session: ignored
    assert c.server_offset_s == 3 * 3600
    later = t0 + 2 * 86400                                                 # quotes resume after weekend
    c._observe_offset("X", int((later + 2 * 3600) * 1000), now=later)
    assert c.server_offset_s == 2 * 3600
