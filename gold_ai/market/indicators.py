"""Indicator and market-structure library used by the strategy setups and the research harness.

Every function reads only the closed bars it is given; callers pass bars the candle builder has already
closed, so nothing here can see the future. Functions return None when there are not enough bars rather
than estimating.

Volume note: MT5 spot-gold "volume" is tick volume (number of quote updates), not traded contracts. VWAP and
volume profile here are therefore *tick-volume weighted* and are labelled so. Centralised futures volume
(COMEX) needs a licensed data source and is not used.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..domain import Candle
from .technical import bollinger, ema_series, macd, rsi, sma

__all__ = ["ema", "ema_slope", "adx", "bollinger_stats", "tick_vwap", "tick_volume_profile", "swing_points",
           "last_swings", "detect_sweep", "range_box", "atr_series", "SwingPoint", "Sweep",
           "bollinger", "macd", "rsi", "sma"]


def ema(values: list[float], n: int) -> float | None:
    s = ema_series(values, n)
    return s[-1] if s else None


def ema_slope(values: list[float], n: int, lookback: int = 5) -> float | None:
    """Change of EMA(n) over the last `lookback` bars (price units)."""
    s = ema_series(values, n)
    if len(s) <= lookback:
        return None
    return s[-1] - s[-1 - lookback]


def atr_series(bars: list[Candle], n: int = 14) -> list[float]:
    """Wilder ATR for every bar from index n onward."""
    if len(bars) < n + 1:
        return []
    trs = [max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)) for p, c in zip(bars, bars[1:])]
    a = sum(trs[:n]) / n
    out = [a]
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
        out.append(a)
    return out


def adx(bars: list[Candle], n: int = 14) -> dict | None:
    """Wilder's ADX with +DI / -DI. Needs 2n+1 bars."""
    if len(bars) < 2 * n + 1:
        return None
    pdm, mdm, trs = [], [], []
    for p, c in zip(bars, bars[1:]):
        up, down = c.high - p.high, p.low - c.low
        pdm.append(up if up > down and up > 0 else 0.0)
        mdm.append(down if down > up and down > 0 else 0.0)
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))
    tr_s, p_s, m_s = sum(trs[:n]), sum(pdm[:n]), sum(mdm[:n])
    dxs = []
    pdi = mdi = 0.0
    for i in range(n, len(trs) + 1):
        if i > n:
            tr_s = tr_s - tr_s / n + trs[i - 1]
            p_s = p_s - p_s / n + pdm[i - 1]
            m_s = m_s - m_s / n + mdm[i - 1]
        pdi = 100 * p_s / tr_s if tr_s > 0 else 0.0
        mdi = 100 * m_s / tr_s if tr_s > 0 else 0.0
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi > 0 else 0.0)
    if len(dxs) < n:
        return None
    a = sum(dxs[:n]) / n
    for dx in dxs[n:]:
        a = (a * (n - 1) + dx) / n
    return {"adx": a, "plus_di": pdi, "minus_di": mdi}


def bollinger_stats(closes: list[float], n: int = 20, k: float = 2.0, history: int = 100) -> dict | None:
    """Bollinger bands plus %B, bandwidth (width / middle) and the bandwidth's percentile over `history` bars
    (low percentile = compression)."""
    bb = bollinger(closes, n, k)
    if bb is None:
        return None
    width = bb["upper"] - bb["lower"]
    pct_b = (closes[-1] - bb["lower"]) / width if width > 0 else 0.5
    bw = width / bb["middle"] if bb["middle"] else 0.0
    past = []
    for end in range(max(n, len(closes) - history), len(closes)):
        b = bollinger(closes[end - n:end], n, k)
        if b is not None and b["middle"]:
            past.append((b["upper"] - b["lower"]) / b["middle"])
    pctile = sum(1 for x in past if x <= bw) / len(past) if past else None
    return {**bb, "pct_b": pct_b, "bandwidth": bw, "bandwidth_pctile": pctile}


def tick_vwap(bars: list[Candle], session_start: datetime) -> float | None:
    """Tick-volume weighted average of typical price since `session_start` (bars opening at or after it)."""
    num = den = 0.0
    for b in bars:
        if b.time >= session_start:
            w = max(b.tick_volume, 1)
            num += (b.high + b.low + b.close) / 3 * w
            den += w
    return num / den if den > 0 else None


def session_start_utc(t: datetime, hour: int = 0) -> datetime:
    """Start of the trading day containing `t` (default 00:00 UTC)."""
    start = t.replace(hour=hour, minute=0, second=0, microsecond=0)
    return start if start <= t else start - timedelta(days=1)


def tick_volume_profile(bars: list[Candle], bins: int = 24, value_area: float = 0.7) -> dict | None:
    """Tick-volume profile over `bars`: point of control and value area (high/low containing `value_area`
    of tick volume). Each bar's volume is spread evenly over its high-low range."""
    if not bars:
        return None
    lo, hi = min(b.low for b in bars), max(b.high for b in bars)
    if hi <= lo:
        return None
    step = (hi - lo) / bins
    hist = [0.0] * bins
    for b in bars:
        a = min(bins - 1, int((b.low - lo) / step))
        z = min(bins - 1, int((b.high - lo) / step))
        share = max(b.tick_volume, 1) / (z - a + 1)
        for i in range(a, z + 1):
            hist[i] += share
    poc = max(range(bins), key=lambda i: hist[i])
    total = sum(hist)
    inc = {poc}
    acc = hist[poc]
    lo_i = hi_i = poc
    while acc < value_area * total and (lo_i > 0 or hi_i < bins - 1):
        below = hist[lo_i - 1] if lo_i > 0 else -1.0
        above = hist[hi_i + 1] if hi_i < bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            acc += hist[hi_i]
            inc.add(hi_i)
        else:
            lo_i -= 1
            acc += hist[lo_i]
            inc.add(lo_i)
    return {"poc": lo + (poc + 0.5) * step, "va_low": lo + lo_i * step, "va_high": lo + (hi_i + 1) * step,
            "label": "tick-volume profile (quote updates, not traded volume)"}


@dataclass(frozen=True)
class SwingPoint:
    index: int
    time: datetime
    price: float
    kind: str          # "high" | "low"


def swing_points(bars: list[Candle], left: int = 3, right: int = 3) -> list[SwingPoint]:
    """Fractal swings: a high greater than `left` bars before and `right` bars after it. A swing is only
    confirmed `right` bars later, so the last `right` bars can never be swings (no look-ahead)."""
    out: list[SwingPoint] = []
    for i in range(left, len(bars) - right):
        h, lo = bars[i].high, bars[i].low
        if all(h > bars[j].high for j in range(i - left, i)) and all(h >= bars[j].high for j in range(i + 1, i + right + 1)):
            out.append(SwingPoint(i, bars[i].time, h, "high"))
        if all(lo < bars[j].low for j in range(i - left, i)) and all(lo <= bars[j].low for j in range(i + 1, i + right + 1)):
            out.append(SwingPoint(i, bars[i].time, lo, "low"))
    return out


def last_swings(bars: list[Candle], left: int = 3, right: int = 3) -> tuple[SwingPoint | None, SwingPoint | None]:
    """Most recent confirmed swing high and swing low."""
    hi = lo = None
    for s in swing_points(bars, left, right):
        if s.kind == "high":
            hi = s
        else:
            lo = s
    return hi, lo


@dataclass(frozen=True)
class Sweep:
    side: str            # "BUY" after a sweep of lows, "SELL" after a sweep of highs
    level: float         # swept swing price
    extreme: float       # wick extreme of the sweeping bar
    swing_time: datetime


def detect_sweep(bars: list[Candle], left: int = 3, right: int = 3, max_age: int = 60) -> Sweep | None:
    """Liquidity sweep on the last closed bar: its wick traded beyond a confirmed swing (within `max_age`
    bars) and it closed back on the other side of that swing. The swing must not have been taken out by an
    earlier bar."""
    if len(bars) < left + right + 2:
        return None
    last = bars[-1]
    prior = bars[:-1]
    swings = [s for s in swing_points(prior, left, right) if s.index >= len(prior) - max_age]
    for s in reversed(swings):
        after = prior[s.index + 1:]
        if s.kind == "low" and all(b.low > s.price for b in after):
            if last.low < s.price and last.close > s.price:
                return Sweep("BUY", s.price, last.low, s.time)
        if s.kind == "high" and all(b.high < s.price for b in after):
            if last.high > s.price and last.close < s.price:
                return Sweep("SELL", s.price, last.high, s.time)
    return None


def range_box(bars: list[Candle], n: int) -> tuple[float, float] | None:
    """High and low of the `n` bars before the last one (the last bar is the one being tested)."""
    if len(bars) < n + 1:
        return None
    w = bars[-n - 1:-1]
    return max(b.high for b in w), min(b.low for b in w)


def zscore(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    m = sum(values) / len(values)
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))
    return (values[-1] - m) / sd if sd > 0 else 0.0
