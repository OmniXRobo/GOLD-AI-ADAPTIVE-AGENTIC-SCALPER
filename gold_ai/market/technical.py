"""Classic indicator summary for the dashboard's Analysis screen.

Computed only from closed candles the engine has already built from real ticks. This is a display
aid: the decision model does not read it. An indicator without enough bars is reported as None
with the number of bars it still needs, never estimated.
"""
from __future__ import annotations

from ..domain import Candle


def sma(values: list[float], n: int) -> float | None:
    return sum(values[-n:]) / n if len(values) >= n else None


def ema_series(values: list[float], n: int) -> list[float]:
    if len(values) < n:
        return []
    k = 2 / (n + 1)
    out = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], n: int = 14) -> float | None:
    """Wilder's RSI."""
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[:n], closes[1:n + 1]):
        d = b - a
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / n, losses / n
    for a, b in zip(closes[n:], closes[n + 1:]):
        d = b - a
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100 - 100 / (1 + ag / al)


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict | None:
    if len(closes) < slow + signal:
        return None
    f, s = ema_series(closes, fast), ema_series(closes, slow)
    line = [a - b for a, b in zip(f[slow - fast:], s)]
    sig = ema_series(line, signal)
    return {"macd": line[-1], "signal": sig[-1], "histogram": line[-1] - sig[-1]}


def stochastic(bars: list[Candle], n: int = 14, d: int = 3) -> dict | None:
    if len(bars) < n + d - 1:
        return None
    ks = []
    for i in range(len(bars) - d + 1, len(bars) + 1):
        win = bars[i - n:i]
        hi, lo = max(b.high for b in win), min(b.low for b in win)
        ks.append(50.0 if hi == lo else (win[-1].close - lo) / (hi - lo) * 100)
    return {"k": ks[-1], "d": sum(ks) / len(ks)}


def bollinger(closes: list[float], n: int = 20, k: float = 2.0) -> dict | None:
    if len(closes) < n:
        return None
    w = closes[-n:]
    mid = sum(w) / n
    sd = (sum((x - mid) ** 2 for x in w) / n) ** 0.5
    return {"upper": mid + k * sd, "middle": mid, "lower": mid - k * sd}


def pressure(bars: list[Candle], n: int = 30) -> dict | None:
    """Share of candle body movement that was upward over the last n bars (a proxy, not order flow)."""
    if len(bars) < n:
        return None
    up = sum(max(b.close - b.open, 0.0) for b in bars[-n:])
    down = sum(max(b.open - b.close, 0.0) for b in bars[-n:])
    total = up + down
    if total == 0:
        return {"buy_pct": 50.0, "sell_pct": 50.0, "bars": n}
    return {"buy_pct": up / total * 100, "sell_pct": down / total * 100, "bars": n}


def _vote(x: float | None, bull: bool | None) -> int | None:
    if x is None or bull is None:
        return None
    return 1 if bull else -1


def summary(bars: list[Candle], timeframe: str) -> dict:
    closes = [b.close for b in bars]
    last = closes[-1] if closes else None
    r = rsi(closes)
    m = macd(closes)
    st = stochastic(bars)
    bb = bollinger(closes)
    s50, s200 = sma(closes, 50), sma(closes, 200)
    pr = pressure(bars)

    votes: dict[str, int] = {}
    if r is not None and not 45 <= r <= 55:
        votes["rsi"] = 1 if r > 55 else -1
    if m is not None:
        votes["macd"] = 1 if m["histogram"] > 0 else -1
    if st is not None and not 40 <= st["k"] <= 60:
        votes["stochastic"] = 1 if st["k"] > 60 else -1
    if s50 is not None and last is not None:
        votes["price_vs_ma50"] = 1 if last > s50 else -1
    if s50 is not None and s200 is not None:
        votes["ma50_vs_ma200"] = 1 if s50 > s200 else -1
    available = sum(x is not None for x in (r, m, st, s50, s200))
    score = sum(votes.values()) / available if available else None
    if score is None:
        label = "insufficient data"
    elif score >= 0.5:
        label = "strong bullish"
    elif score >= 0.2:
        label = "bullish"
    elif score <= -0.5:
        label = "strong bearish"
    elif score <= -0.2:
        label = "bearish"
    else:
        label = "neutral"

    need = {"rsi": 15, "macd": 35, "stochastic": 16, "bollinger": 20, "ma50": 50, "ma200": 200, "pressure": 30}
    missing = {k: v - len(bars) for k, v in need.items() if len(bars) < v}
    support = resistance = None
    if bb is not None and last is not None:
        support = bb["lower"] if bb["lower"] < last else None
        resistance = bb["upper"] if bb["upper"] > last else None
    return {
        "timeframe": timeframe, "bars": len(bars),
        "last_close": last, "last_bar_time": bars[-1].time.isoformat() if bars else None,
        "rsi14": r, "macd": m, "stochastic": st, "bollinger": bb, "ma50": s50, "ma200": s200,
        "pressure": pr, "votes": votes, "score": score, "label": label,
        "support": support, "resistance": resistance, "bars_missing": missing,
        "note": "Indicative summary from closed candles built from real ticks; not used by the decision model.",
    }


__all__ = ["rsi", "macd", "stochastic", "bollinger", "sma", "pressure", "summary"]
