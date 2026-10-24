"""Read-only MetaTrader 5 market-data connector.

Wraps the official `MetaTrader5` Python package (Windows only). This class
deliberately exposes NO order-sending method: execution lives in a separate,
authorization-gated adapter (see execution.py). The module object is injectable
so the connector can be tested with a fake on Linux/CI.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..domain import Candle, SymbolSpec, Tick
from .symbols import discover_gold_symbols, discover_instrument

log = logging.getLogger(__name__)

# MT5 enum values (from MetaTrader5 package docs) used when mapping metadata.
_TRADE_MODES = {0: "disabled", 1: "longonly", 2: "shortonly", 3: "closeonly", 4: "full"}
_SWAP_MODES = {1: "points", 2: "money", 3: "money", 4: "money"}  # base/margin/deposit currency
_EXEC_MODES = {0: "request", 1: "instant", 2: "market", 3: "exchange"}
_FILLING_FLAGS = {1: "FOK", 2: "IOC", 4: "BOC"}
_ACCOUNT_TRADE_MODES = {0: "demo", 1: "contest", 2: "real"}


@dataclass
class BrokerProfile:
    """Static hints for a broker. Never used instead of live metadata."""

    name: str
    server_patterns: tuple[str, ...]
    symbol_hints: tuple[str, ...] = ()
    commission_per_lot_side: float = 0.0   # override when the broker charges outside symbol info
    notes: str = ""


BROKER_PROFILES: dict[str, BrokerProfile] = {
    "exness": BrokerProfile("Exness", ("Exness",), ("XAUUSDm", "XAUUSD", "XAUUSDc"),
                            notes="Account types use symbol suffixes (m, c, ...). Raw/Zero accounts charge commission."),
    "equiti": BrokerProfile("Equiti", ("Equiti",), ("XAUUSD", "XAUUSD.a")),
    "multibank": BrokerProfile("MultiBank", ("MultiBank", "MEXAtlantic", "MEX"), ("XAUUSD", "GOLD")),
}


def identify_broker(server: str, company: str = "") -> str:
    hay = f"{server} {company}".lower()
    for key, prof in BROKER_PROFILES.items():
        if any(p.lower() in hay for p in prof.server_patterns):
            return key
    return "generic"


@dataclass
class AccountSnapshot:
    broker: str
    server: str
    login: str
    currency: str
    trade_mode: str              # demo / contest / real
    trade_allowed: bool
    balance: float
    equity: float
    leverage: int
    company: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_real(self) -> bool:
        return self.trade_mode == "real"


# MT5 stamps ticks in broker *server* time encoded as if it were UTC (e.g. MetaQuotes-Demo is UTC+3
# in summer). Offsets are whole or half hours; a fresh tick lets us measure the current one.
_OFFSET_STEP_S = 1800
_OFFSET_MAX_S = 14 * 3600
_FRESH_TICK_S = 60
_REMEASURE_GAP_S = 1800


class MT5ReadOnlyConnector:
    """Times returned by this connector are true UTC.

    `server_utc_offset_hours=None` (default) measures the broker's server-time offset from live
    ticks: an offset is accepted only from a tick that just changed (so a closed market's stale
    last quote is never used) and that sits within a minute of a whole/half-hour offset. It is
    re-measured when quotes resume after a pause of 30+ minutes (daylight-saving switches happen
    while gold is closed), never mid-session, so tick times cannot jump. Until it is known,
    `latest_tick` returns None and `ticks_range` raises. Pass a number to pin the offset.
    """

    def __init__(self, mt5_module: Any | None = None, terminal_path: str | None = None,
                 server_utc_offset_hours: float | None = None):
        if mt5_module is None:
            try:
                import MetaTrader5 as mt5_module  # type: ignore
            except ImportError as e:  # pragma: no cover - environment dependent
                raise RuntimeError("MetaTrader5 package not available (Windows + MT5 terminal required)") from e
        self.mt5 = mt5_module
        self.terminal_path = terminal_path
        self.connected = False
        self.last_latency_ms: float | None = None
        self.offset_pinned = server_utc_offset_hours is not None
        self.server_offset_s: int | None = (int(round(server_utc_offset_hours * 3600))
                                            if server_utc_offset_hours is not None else None)
        self._last_raw_msc: dict[str, int] = {}
        self._last_move_wall: dict[str, float] = {}

    # -- server time ---------------------------------------------------------
    @property
    def server_offset_known(self) -> bool:
        return self.server_offset_s is not None

    def _observe_offset(self, symbol: str, raw_msc: int, now: float | None = None) -> None:
        if self.offset_pinned:
            return
        now = time.time() if now is None else now
        prev = self._last_raw_msc.get(symbol)
        self._last_raw_msc[symbol] = raw_msc
        if prev is None or raw_msc == prev:
            return  # need a tick that just arrived, not a stale last quote
        # Per symbol: Bitcoin quotes through the weekend, so its stream never pauses; the offset is then
        # re-measured when gold/forex quotes resume after their own weekend pause.
        last_move = self._last_move_wall.get(symbol)
        self._last_move_wall[symbol] = now
        if self.server_offset_known and last_move is not None and now - last_move < _REMEASURE_GAP_S:
            return  # only re-measure after a market pause (weekend/daily break), so time never jumps mid-session
        diff = raw_msc / 1000.0 - now
        candidate = int(round(diff / _OFFSET_STEP_S) * _OFFSET_STEP_S)
        if abs(diff - candidate) > _FRESH_TICK_S or abs(candidate) > _OFFSET_MAX_S:
            return
        if candidate != self.server_offset_s:
            log.info("broker server time offset: UTC%+.1fh", candidate / 3600)
            self.server_offset_s = candidate

    def _to_utc(self, raw_msc: int) -> datetime:
        return datetime.fromtimestamp(raw_msc / 1000.0 - (self.server_offset_s or 0), tz=timezone.utc)

    def server_time_info(self) -> dict:
        return {"offset_hours": None if self.server_offset_s is None else self.server_offset_s / 3600,
                "pinned": self.offset_pinned}

    # -- connection -------------------------------------------------------
    def connect(self, login: int | None = None, password: str | None = None, server: str | None = None) -> bool:
        kwargs: dict[str, Any] = {}
        if self.terminal_path:
            kwargs["path"] = self.terminal_path
        if login:
            kwargs.update(login=login, password=password, server=server)
        ok = bool(self.mt5.initialize(**kwargs))
        if not ok:
            log.error("MT5 initialize failed: %s", self.mt5.last_error())
        self.connected = ok
        return ok

    def shutdown(self) -> None:
        self.mt5.shutdown()
        self.connected = False

    def health(self) -> dict:
        t0 = time.perf_counter()
        info = self.mt5.terminal_info()
        self.last_latency_ms = (time.perf_counter() - t0) * 1000
        if info is None:
            return {"connected": False, "error": str(self.mt5.last_error())}
        return {
            "connected": bool(getattr(info, "connected", False)),
            "trade_allowed": bool(getattr(info, "trade_allowed", False)),
            "ping_ms": getattr(info, "ping_last", 0) / 1000.0,
            "api_latency_ms": round(self.last_latency_ms, 3),
        }

    # -- account / symbols -------------------------------------------------
    def account(self) -> AccountSnapshot:
        a = self.mt5.account_info()
        if a is None:
            raise RuntimeError(f"account_info failed: {self.mt5.last_error()}")
        broker = identify_broker(a.server, getattr(a, "company", ""))
        return AccountSnapshot(
            broker=broker, server=a.server, login=str(a.login), currency=a.currency,
            trade_mode=_ACCOUNT_TRADE_MODES.get(a.trade_mode, "unknown"),
            trade_allowed=bool(a.trade_allowed), balance=a.balance, equity=a.equity,
            leverage=a.leverage, company=getattr(a, "company", ""),
        )

    def discover_gold(self) -> list[str]:
        symbols = self.mt5.symbols_get() or []
        return [c.name for c in discover_gold_symbols(symbols)]

    def discover(self, instrument: str, prefer_suffix: str | None = None) -> list[str]:
        """Broker symbols validated as a canonical instrument (XAUUSD, BTCUSD, EURUSD ...), best first."""
        symbols = self.mt5.symbols_get() or []
        return [c.name for c in discover_instrument(symbols, instrument, prefer_suffix)]

    def symbol_spec(self, symbol: str, broker: str) -> SymbolSpec:
        if not self.mt5.symbol_select(symbol, True):
            raise RuntimeError(f"symbol_select({symbol}) failed: {self.mt5.last_error()}")
        s = self.mt5.symbol_info(symbol)
        if s is None:
            raise RuntimeError(f"symbol_info({symbol}) failed")
        fillings = tuple(n for flag, n in _FILLING_FLAGS.items() if s.filling_mode & flag)
        prof = BROKER_PROFILES.get(broker)
        return SymbolSpec(
            broker=broker, symbol=symbol, digits=s.digits, point=s.point,
            tick_size=s.trade_tick_size, tick_value=s.trade_tick_value,
            contract_size=s.trade_contract_size, volume_min=s.volume_min,
            volume_max=s.volume_max, volume_step=s.volume_step,
            stops_level_points=s.trade_stops_level, freeze_level_points=s.trade_freeze_level,
            swap_long=s.swap_long, swap_short=s.swap_short,
            swap_mode=_SWAP_MODES.get(s.swap_mode, "points"),
            commission_per_lot_side=prof.commission_per_lot_side if prof else 0.0,
            margin_initial=getattr(s, "margin_initial", 0.0),
            currency_base=s.currency_base, currency_profit=s.currency_profit,
            trade_mode=_TRADE_MODES.get(s.trade_mode, "unknown"),
            filling_modes=fillings, execution_mode=_EXEC_MODES.get(s.trade_exemode, "unknown"),
        )

    # -- market data --------------------------------------------------------
    def latest_tick(self, symbol: str) -> Tick | None:
        t = self.mt5.symbol_info_tick(symbol)
        if t is None:
            return None
        self._observe_offset(symbol, int(t.time_msc))
        if not self.server_offset_known:
            return None
        return Tick(self._to_utc(int(t.time_msc)), t.bid, t.ask,
                    float(getattr(t, "volume_real", 0.0) or getattr(t, "volume", 0)))

    def ticks_range(self, symbol: str, start: datetime, end: datetime) -> list[Tick]:
        """Ticks between UTC `start` and `end` (converted to and from broker server time)."""
        if not self.server_offset_known:
            raise RuntimeError("broker server time offset not known yet (needs a live tick)")
        off = timedelta(seconds=self.server_offset_s)
        flags = getattr(self.mt5, "COPY_TICKS_ALL", -1)
        arr = self.mt5.copy_ticks_range(symbol, start + off, end + off, flags)
        if arr is None:
            raise RuntimeError(f"copy_ticks_range failed: {self.mt5.last_error()}")
        out = []
        for r in arr:
            bid, ask = float(r["bid"]), float(r["ask"])
            if bid <= 0 or ask <= 0:
                continue  # MT5 emits last-only ticks with zero bid/ask
            out.append(Tick(self._to_utc(int(r["time_msc"])),
                            bid, ask, float(r["volume_real"]) if "volume_real" in r.dtype.names else 0.0))
        return out

    def rates(self, symbol: str, timeframe: str, count: int = 500) -> list[Candle]:
        """The broker's most recent `count` bars (Bid based, like MT5 charts), oldest first, in UTC.

        Read-only (copy_rates_from_pos). The newest bar is usually still forming; callers keep only bars
        that have closed. Returns [] when the terminal cannot provide them or the server-time offset is
        not known yet, so bars are never placed at the wrong time.
        """
        if not self.server_offset_known:
            self.latest_tick(symbol)
            if not self.server_offset_known:
                return []
        tf = getattr(self.mt5, f"TIMEFRAME_{timeframe}", None)
        fn = getattr(self.mt5, "copy_rates_from_pos", None)
        if tf is None or fn is None:
            return []
        arr = fn(symbol, tf, 0, count)
        if arr is None:
            log.warning("copy_rates_from_pos(%s, %s) failed: %s", symbol, timeframe, self.mt5.last_error())
            return []
        out = []
        for r in arr:
            out.append(Candle(self._to_utc(int(r["time"]) * 1000), float(r["open"]), float(r["high"]),
                              float(r["low"]), float(r["close"]), int(r["tick_volume"])))
        return out
