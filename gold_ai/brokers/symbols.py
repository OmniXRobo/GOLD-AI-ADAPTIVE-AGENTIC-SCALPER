"""Gold symbol discovery.

Broker symbol names vary (XAUUSD, XAUUSDm, XAUUSD.a, GOLD, XAUUSD+ ...). Names are
only used to shortlist candidates; a candidate is accepted only when the broker's
own metadata confirms it is spot gold quoted in USD (base XAU / profit USD, or a
description that says gold, plus a plausible contract size).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

_NAME_PATTERN = re.compile(r"^(XAUUSD|GOLD)([._\-+#]?[A-Za-z0-9]{0,6})?$", re.IGNORECASE)
_EXCLUDE = re.compile(r"(XAUEUR|XAUAUD|XAUGBP|XAUJPY|XAUCHF|XAUXAG|GOLDEUR|FUT|_F$|OPT)", re.IGNORECASE)
# Spot gold CFDs are almost always 100 oz per lot; some brokers use 1, 10 or 1000.
_PLAUSIBLE_CONTRACT_SIZES = {1.0, 10.0, 100.0, 1000.0}


@dataclass(frozen=True)
class GoldCandidate:
    name: str
    score: int
    reasons: tuple[str, ...]
    rejected: bool = False


def _get(meta: Any, key: str, default: Any = None) -> Any:
    if isinstance(meta, Mapping):
        return meta.get(key, default)
    return getattr(meta, key, default)


def evaluate_symbol(meta: Any) -> GoldCandidate:
    """Score one symbol's metadata (MT5 symbol_info object or dict)."""
    name = str(_get(meta, "name", ""))
    reasons: list[str] = []
    score = 0
    if _EXCLUDE.search(name):
        return GoldCandidate(name, 0, ("excluded cross/future pattern",), rejected=True)
    if _NAME_PATTERN.match(name):
        score += 1
        reasons.append("name matches gold alias")
    base = str(_get(meta, "currency_base", "") or "").upper()
    profit = str(_get(meta, "currency_profit", "") or "").upper()
    desc = str(_get(meta, "description", "") or "").lower()
    path = str(_get(meta, "path", "") or "").lower()
    if base == "XAU":
        score += 3
        reasons.append("base currency XAU")
    elif "gold" in desc or "metal" in path:
        score += 1
        reasons.append("description/path mentions gold/metals")
    if profit == "USD":
        score += 2
        reasons.append("profit currency USD")
    elif profit:
        return GoldCandidate(name, score, tuple(reasons + [f"profit currency {profit} != USD"]), rejected=True)
    contract = _get(meta, "trade_contract_size", None)
    if contract is not None:
        if float(contract) in _PLAUSIBLE_CONTRACT_SIZES:
            score += 1
            reasons.append(f"contract size {contract}")
        else:
            reasons.append(f"unusual contract size {contract}")
    if _get(meta, "trade_mode", None) == 0:  # SYMBOL_TRADE_MODE_DISABLED
        reasons.append("trading disabled on symbol")
        score -= 1
    rejected = score < 4 or not (base == "XAU" or "gold" in desc)
    return GoldCandidate(name, score, tuple(reasons), rejected=rejected)


def discover_gold_symbols(symbols: Iterable[Any]) -> list[GoldCandidate]:
    """Return accepted gold symbols, best first. Empty list means none validated."""
    out = [evaluate_symbol(s) for s in symbols]
    accepted = [c for c in out if not c.rejected]
    # Prefer plain names (shortest) at equal score so XAUUSD beats XAUUSD.ecn variants.
    accepted.sort(key=lambda c: (-c.score, len(c.name), c.name))
    return accepted


def evaluate_instrument(meta: Any, instrument: str) -> GoldCandidate:
    """Score one symbol's metadata as a candidate for a canonical instrument (XAUUSD, BTCUSD, EURUSD ...).

    The name only shortlists; base and profit currency from the broker must match the instrument
    (crypto CFDs may report a non-crypto base, then the description must name the coin).
    """
    from ..instruments import INSTRUMENTS, canonical
    if instrument == "XAUUSD":
        return evaluate_symbol(meta)
    inst = INSTRUMENTS[instrument]
    name = str(_get(meta, "name", ""))
    if canonical(name) != instrument:
        return GoldCandidate(name, 0, ("name does not match",), rejected=True)
    base = str(_get(meta, "currency_base", "") or "").upper()
    profit = str(_get(meta, "currency_profit", "") or "").upper()
    desc = str(_get(meta, "description", "") or "").lower()
    reasons, score = ["name matches"], 1
    if profit and profit != inst.quote:
        return GoldCandidate(name, score, tuple(reasons + [f"profit currency {profit} != {inst.quote}"]), rejected=True)
    if profit == inst.quote:
        score += 2
        reasons.append(f"profit currency {profit}")
    if base == inst.base:
        score += 3
        reasons.append(f"base currency {base}")
    elif any(w in desc for w in inst.description_words):
        score += 2
        reasons.append(f"description names {inst.base}")
    else:
        return GoldCandidate(name, score, tuple(reasons + [f"base currency {base or '?'} != {inst.base}"]), rejected=True)
    if _get(meta, "trade_mode", None) == 0:
        reasons.append("trading disabled on symbol")
        score -= 1
    return GoldCandidate(name, score, tuple(reasons), rejected=score < 4)


def discover_instrument(symbols: Iterable[Any], instrument: str, prefer_suffix: str | None = None) -> list[GoldCandidate]:
    """Broker symbols validated as `instrument`, best first. A symbol with `prefer_suffix` (the gold symbol's
    account-type suffix, e.g. ".sd") ranks first so every instrument comes from the same account type."""
    from ..instruments import suffix_of
    accepted = [c for c in (evaluate_instrument(s, instrument) for s in symbols) if not c.rejected]
    accepted.sort(key=lambda c: (prefer_suffix is not None and suffix_of(c.name).lower() != prefer_suffix.lower(),
                                 -c.score, len(c.name), c.name))
    return accepted
