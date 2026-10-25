"""Market Intelligence Agent: causal feature extraction and regime detection.

All features are computed only from ticks/bars already observed. Indicators here
are inputs to the adaptive decision model, not trading rules on their own.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from ..domain import Candle, Tick
from .candles import MultiTimeframeBuilder

FEATURE_NAMES = (
    "tick_velocity", "tick_accel", "vol_short", "vol_ratio", "spread_z",
    "mom_m1_5", "mom_m5_3", "mom_m15_3", "body_ratio_m1", "wick_bias_m1",
    "dist_res_atr", "dist_sup_atr", "efficiency_m5", "atr_m1", "atr_m5",
)

REGIMES = ("trending_up", "trending_down", "ranging", "volatile", "quiet", "unknown")


def atr(bars: list[Candle], n: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    trs = []
    for prev, cur in zip(bars[-n - 1:-1], bars[-n:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(trs) / len(trs) if trs else 0.0


def efficiency_ratio(bars: list[Candle], n: int = 20) -> float:
    """Kaufman efficiency: |net move| / sum(|moves|). 1 = clean trend, 0 = chop."""
    closes = [b.close for b in bars[-n - 1:]]
    if len(closes) < 3:
        return 0.0
    path = sum(abs(b - a) for a, b in zip(closes, closes[1:]))
    return abs(closes[-1] - closes[0]) / path if path > 0 else 0.0


def _ret(bars: list[Candle], k: int, scale: float) -> float:
    if len(bars) <= k or scale <= 0:
        return 0.0
    return (bars[-1].close - bars[-1 - k].close) / scale


@dataclass
class MarketState:
    features: dict[str, float]
    regime: str
    ready: bool
    last_tick: Tick | None
    # Closed bars per timeframe (a live reference to the builder's lists; read-only for consumers).
    bars: dict[str, list[Candle]] | None = None


class MarketIntelligenceAgent:
    """Consumes ticks, maintains multi-timeframe bars, emits a feature vector.

    `timeframes` are the (fast, base, slow) bars the bar features use. Feature names keep the scalping
    timeframes (mom_m1_5 = fast, mom_m5_3 / atr_m5 = base, mom_m15_3 = slow) so every trade style shares
    one model schema; a swing agent with ("M15", "H1", "H4") reads atr_m5 as the hourly ATR.
    """

    def __init__(self, tick_window: int = 300, warmup_m5_bars: int = 20,
                 timeframes: tuple[str, str, str] = ("M1", "M5", "M15"), bar_timeframes: tuple[str, ...] | None = None):
        # bar_timeframes limits which bars are built (research speed); default builds M1..D1 for the dashboard.
        self.mtf = MultiTimeframeBuilder(bar_timeframes) if bar_timeframes else MultiTimeframeBuilder()
        missing = [tf for tf in timeframes if tf not in self.mtf.bars]
        if len(timeframes) != 3 or missing:
            raise ValueError(f"need three known timeframes (fast, base, slow), got {timeframes}")
        self.timeframes = tuple(timeframes)
        self.ticks: deque[Tick] = deque(maxlen=tick_window)
        self.spreads: deque[float] = deque(maxlen=2000)
        self.warmup_m5_bars = warmup_m5_bars
        self._prev_velocity = 0.0

    def on_tick(self, tick: Tick) -> dict[str, Candle]:
        self.ticks.append(tick)
        self.spreads.append(tick.spread)
        return self.mtf.update(tick)

    @property
    def ready(self) -> bool:
        return len(self.mtf.bars[self.timeframes[1]]) >= self.warmup_m5_bars and len(self.ticks) >= 30

    def state(self, advance: bool = False) -> MarketState:
        """Current features. Only the trading loop passes advance=True: tick_accel is the change in tick
        velocity since the previous decision, so a dashboard read must not move that reference point."""
        bars = self.mtf.bars
        m1, m5, m15 = (bars[tf] for tf in self.timeframes)   # fast, base, slow
        last = self.ticks[-1] if self.ticks else None
        ready = self.ready
        f = dict.fromkeys(FEATURE_NAMES, 0.0)
        if not ready or last is None:
            return MarketState(f, "unknown", False, last)

        a1, a5 = atr(m1), atr(m5)
        scale = a5 or a1 or 1e-9
        ticks = list(self.ticks)
        win = ticks[-30:]
        dt = max((win[-1].time - win[0].time).total_seconds(), 1e-3)
        vel = (win[-1].mid - win[0].mid) / dt / scale
        f["tick_velocity"] = vel
        f["tick_accel"] = vel - self._prev_velocity
        if advance:
            self._prev_velocity = vel

        rets = [b.mid - a.mid for a, b in zip(ticks, ticks[1:])]
        short = rets[-50:]
        vs = _std(short)
        vl = _std(rets)
        f["vol_short"] = vs / scale
        f["vol_ratio"] = vs / vl if vl > 0 else 1.0

        sp = list(self.spreads)
        mu, sd = sum(sp) / len(sp), _std(sp)
        f["spread_z"] = (last.spread - mu) / sd if sd > 0 else 0.0

        f["mom_m1_5"] = _ret(m1, 5, scale)
        f["mom_m5_3"] = _ret(m5, 3, scale)
        f["mom_m15_3"] = _ret(m15, 3, scale) if len(m15) > 3 else 0.0
        if m1:
            b = m1[-1]
            rng = b.high - b.low
            if rng > 0:
                f["body_ratio_m1"] = (b.close - b.open) / rng
                f["wick_bias_m1"] = ((min(b.open, b.close) - b.low) - (b.high - max(b.open, b.close))) / rng
        look = m5[-50:]
        res, sup = max(b.high for b in look), min(b.low for b in look)
        f["dist_res_atr"] = (res - last.bid) / scale
        f["dist_sup_atr"] = (last.bid - sup) / scale
        f["efficiency_m5"] = efficiency_ratio(m5)
        f["atr_m1"] = a1
        f["atr_m5"] = a5
        return MarketState(f, classify_regime(f, m5), True, last, bars)


def classify_regime(f: dict[str, float], m5: list[Candle]) -> str:
    if len(m5) < 10:
        return "unknown"
    if f["vol_ratio"] > 2.0:
        return "volatile"
    if f["vol_ratio"] < 0.4:
        return "quiet"
    if f["efficiency_m5"] > 0.35:
        return "trending_up" if m5[-1].close > m5[-20 if len(m5) >= 20 else 0].close else "trending_down"
    return "ranging"


def _std(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
