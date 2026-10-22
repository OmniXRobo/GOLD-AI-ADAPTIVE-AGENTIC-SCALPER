from datetime import datetime, timezone

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
    c = MT5ReadOnlyConnector(fake)
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
