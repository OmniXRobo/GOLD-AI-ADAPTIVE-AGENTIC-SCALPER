"""Synthetic market feed for tests and offline development ONLY.

Data from this module is random and must never be presented as historical gold
data or used to report strategy performance. Every tick stream it produces is
tagged with source="synthetic" by callers that persist it.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Iterator

from ..domain import SymbolSpec, Tick

SYNTHETIC_SOURCE = "synthetic"


def synthetic_spec(broker: str = "mock", symbol: str = "XAUUSD", commission: float = 3.5) -> SymbolSpec:
    """A plausible XAUUSD spec (100 oz/lot, 2 digits). For tests only."""
    return SymbolSpec(
        broker=broker, symbol=symbol, digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
        contract_size=100.0, volume_min=0.01, volume_max=100.0, volume_step=0.01,
        stops_level_points=20, swap_long=-50.0, swap_short=20.0, swap_mode="points",
        commission_per_lot_side=commission,
    )


def synthetic_ticks(
    n: int,
    start: datetime | None = None,
    price: float = 2400.0,
    spread: float = 0.20,
    step_seconds: float = 1.0,
    vol: float = 0.15,
    drift: float = 0.0,
    seed: int = 7,
    regime_switch_every: int = 0,
) -> Iterator[Tick]:
    rng = random.Random(seed)
    t = start or datetime(2024, 1, 2, 8, 0, tzinfo=timezone.utc)
    d = drift
    for i in range(n):
        if regime_switch_every and i and i % regime_switch_every == 0:
            d = rng.choice([-1, 1]) * abs(drift or 0.02)
        price = max(1.0, price + d + rng.gauss(0, vol))
        sp = spread * (1 + abs(rng.gauss(0, 0.2)))
        bid = round(price - sp / 2, 2)
        ask = round(bid + max(0.01, round(sp, 2)), 2)
        yield Tick(t, bid, ask, 1.0)
        t += timedelta(seconds=step_seconds)


class FakeMT5:
    """Minimal stand-in for the MetaTrader5 module used by connector tests."""

    COPY_TICKS_ALL = -1

    class _Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def __init__(self, symbols: list[dict], ticks: dict[str, Tick] | None = None, trade_mode: int = 0,
                 server: str = "Exness-MT5Trial", company: str = "Exness Technologies Ltd"):
        self._symbols = symbols
        self._ticks = ticks or {}
        self._trade_mode = trade_mode
        self._server = server
        self._company = company
        self.initialized = False
        self.order_send_calls = 0

    def initialize(self, **kw):
        self.initialized = True
        return True

    def shutdown(self):
        self.initialized = False

    def last_error(self):
        return (0, "ok")

    def terminal_info(self):
        return self._Obj(connected=True, trade_allowed=False, ping_last=12000)

    def account_info(self):
        return self._Obj(login=12345, server=self._server, currency="USD", trade_mode=self._trade_mode,
                         trade_allowed=True, balance=10000.0, equity=10000.0, leverage=500, company=self._company)

    def symbols_get(self):
        return [self._Obj(**s) for s in self._symbols]

    def symbol_select(self, name, enable):
        return any(s["name"] == name for s in self._symbols)

    def symbol_info(self, name):
        for s in self._symbols:
            if s["name"] == name:
                base = dict(digits=2, point=0.01, trade_tick_size=0.01, trade_tick_value=1.0,
                            trade_contract_size=100.0, volume_min=0.01, volume_max=200.0, volume_step=0.01,
                            trade_stops_level=0, trade_freeze_level=0, swap_long=-40.0, swap_short=15.0,
                            swap_mode=1, filling_mode=3, trade_exemode=2, trade_mode=4, margin_initial=0.0,
                            currency_base="XAU", currency_profit="USD")
                base.update(s)
                return self._Obj(**base)
        return None

    def symbol_info_tick(self, name):
        t = self._ticks.get(name)
        if t is None:
            return None
        return self._Obj(time_msc=int(t.time.timestamp() * 1000), bid=t.bid, ask=t.ask, volume_real=t.volume)

    def order_send(self, request):  # pragma: no cover - must never be reached by read-only code
        self.order_send_calls += 1
        raise AssertionError("order_send called on read-only path")
