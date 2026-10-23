"""Supported instruments: XAUUSD, BTCUSD and the seven major forex pairs.

Each instrument carries the parts that are not in broker metadata: what a pip is, which
UTC hours it may be traded in, the spread/slippage limits in pips, which currencies' news
can black it out, and how the broker's symbol is recognised. Contract size, tick value,
digits, swaps and volume limits still come only from the broker (`SymbolSpec`).

XAUUSD has no overrides, so gold keeps using the global `RiskConfig`/`CostConfig` values
it was tuned with. Values here are starting limits; the owner can change any of them per
symbol in config (`instrument_overrides`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .config import Settings
    from .domain import SymbolSpec

FOREX_ROLLOVER_AVOID = (20.75, 22.25)   # spreads widen around the 21:00-22:00 UTC rollover


@dataclass(frozen=True)
class Instrument:
    name: str                       # canonical name, e.g. "EURUSD"
    asset_class: str                # metal / crypto / forex
    base: str
    quote: str
    pip_size: float                 # price units per pip (display + pip-based limits)
    display_digits: int             # decimals used to show prices
    max_spread_pips: float | None = None
    slippage_pips: float | None = None          # per side, adverse
    stop_slippage_extra_pips: float | None = None
    sessions_utc: tuple[tuple[float, float], ...] | None = None   # None = use RiskConfig
    trades_weekends: bool = False
    news_currencies: tuple[str, ...] | None = None                # None = every currency
    triple_swap_weekday: int | None = 2         # Wednesday; None = no triple-swap day
    aliases: tuple[str, ...] = ()
    description_words: tuple[str, ...] = ()     # accepted in the broker description when base differs

    def to_dict(self) -> dict:
        return {"name": self.name, "asset_class": self.asset_class, "base": self.base, "quote": self.quote,
                "pip_size": self.pip_size, "display_digits": self.display_digits,
                "max_spread_pips": self.max_spread_pips, "slippage_pips": self.slippage_pips,
                "sessions_utc": [list(s) for s in self.sessions_utc] if self.sessions_utc else None,
                "trades_weekends": self.trades_weekends,
                "news_currencies": list(self.news_currencies) if self.news_currencies else None}


def _fx(pair: str, max_spread: float, sessions: tuple[tuple[float, float], ...]) -> Instrument:
    jpy = pair.endswith("JPY")
    return Instrument(pair, "forex", pair[:3], pair[3:], 0.01 if jpy else 0.0001, 3 if jpy else 5,
                      max_spread_pips=max_spread, slippage_pips=0.2, stop_slippage_extra_pips=0.5,
                      sessions_utc=sessions, news_currencies=(pair[:3], pair[3:]))


# London + New York for European pairs; Asia + London + New York for JPY/AUD/NZD; New York-led for CAD.
_EUROPE = ((6.0, FOREX_ROLLOVER_AVOID[0]),)
_ASIA_TO_NY = ((0.0, FOREX_ROLLOVER_AVOID[0]), (FOREX_ROLLOVER_AVOID[1], 24.0))
_NY = ((11.0, FOREX_ROLLOVER_AVOID[0]),)

INSTRUMENTS: dict[str, Instrument] = {i.name: i for i in (
    Instrument("XAUUSD", "metal", "XAU", "USD", 0.1, 2, aliases=("GOLD",), description_words=("gold",)),
    Instrument("BTCUSD", "crypto", "BTC", "USD", 1.0, 2, max_spread_pips=60.0, slippage_pips=5.0,
               stop_slippage_extra_pips=10.0, sessions_utc=((0.0, 24.0),), trades_weekends=True,
               news_currencies=("USD",), triple_swap_weekday=None, aliases=("BITCOIN",),
               description_words=("bitcoin",)),
    _fx("EURUSD", 2.0, _EUROPE),
    _fx("GBPUSD", 2.5, _EUROPE),
    _fx("USDCHF", 2.5, _EUROPE),
    _fx("USDJPY", 2.0, _ASIA_TO_NY),
    _fx("AUDUSD", 2.0, _ASIA_TO_NY),
    _fx("NZDUSD", 3.0, _ASIA_TO_NY),
    _fx("USDCAD", 2.5, _NY),
)}

DEFAULT_SYMBOLS = tuple(INSTRUMENTS)

_SUFFIX = r"([._\-+#]?[A-Za-z0-9]{0,6})?"


def canonical(symbol: str) -> str | None:
    """Canonical instrument for a broker symbol name (XAUUSD.sd -> XAUUSD, EURUSDm -> EURUSD), or None."""
    for inst in INSTRUMENTS.values():
        for n in (inst.name, *inst.aliases):
            if re.fullmatch(re.escape(n) + _SUFFIX, symbol, re.IGNORECASE):
                return inst.name
    return None


def suffix_of(symbol: str) -> str:
    """The broker's account-type suffix (".sd" in XAUUSD.sd, "m" in EURUSDm)."""
    c = canonical(symbol)
    if c is None:
        return ""
    for n in (c, *INSTRUMENTS[c].aliases):
        if symbol.upper().startswith(n):
            return symbol[len(n):]
    return ""


def instrument_for(symbol: str, settings: "Settings | None" = None) -> Instrument | None:
    c = canonical(symbol)
    if c is None:
        return None
    inst = INSTRUMENTS[c]
    over = (settings.instrument_overrides.get(c) if settings is not None else None) or {}
    if over:
        over = {k: (tuple(tuple(x) for x in v) if k == "sessions_utc" and v else
                    tuple(v) if k == "news_currencies" and v else v)
                for k, v in over.items() if k in Instrument.__dataclass_fields__ and k != "name"}
        inst = replace(inst, **over)
    return inst


def pip_size(symbol: str) -> float | None:
    inst = instrument_for(symbol)
    return inst.pip_size if inst else None


def settings_for(settings: "Settings", spec: "SymbolSpec") -> "Settings":
    """Settings with risk/cost limits converted to this symbol (pips -> broker points).

    Unknown symbols and XAUUSD get the settings unchanged.
    """
    inst = instrument_for(spec.symbol, settings)
    if inst is None or spec.point <= 0:
        return settings
    pts = lambda pips: max(0, round(pips * inst.pip_size / spec.point))  # noqa: E731
    risk: dict = {}
    costs: dict = {}
    if inst.max_spread_pips is not None:
        risk["max_spread_points"] = pts(inst.max_spread_pips)
    if inst.sessions_utc is not None:
        risk["allowed_sessions_utc"] = [tuple(s) for s in inst.sessions_utc]
    if inst.news_currencies is not None:
        risk["news_currencies"] = list(inst.news_currencies)
    if inst.slippage_pips is not None:
        costs["slippage_points_entry"] = costs["slippage_points_exit"] = pts(inst.slippage_pips)
        risk["max_slippage_points"] = max(settings.risk.max_slippage_points, 3 * pts(inst.slippage_pips))
    if inst.stop_slippage_extra_pips is not None:
        costs["stop_slippage_extra_points"] = pts(inst.stop_slippage_extra_pips)
    costs["triple_swap_weekday"] = inst.triple_swap_weekday
    return settings.model_copy(update={"risk": settings.risk.model_copy(update=risk),
                                       "costs": settings.costs.model_copy(update=costs)})
