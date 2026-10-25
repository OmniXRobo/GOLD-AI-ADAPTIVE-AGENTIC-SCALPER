"""Strategy library: versioned trade setups for XAUUSD scalping.

A setup is a *hypothesis*, not a trading rule the bot trusts. It proposes a side and a structural stop
(beyond the swing, range or sweep extreme that would prove the idea wrong). Whether a setup is ever used for
signals is decided by the research harness (`gold_ai.research.setup_eval`) on data it was not tuned on,
after costs, against a random-entry baseline with the same bracket.

Indicators have one role each inside a setup (trend filter, location or trigger) instead of being stacked
into a vote. All inputs are closed bars: decisions are taken when an M1 bar closes and fill on the next tick.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..domain import Candle, Side, Tick
from ..market.features import atr
from ..market.indicators import (adx, bollinger, bollinger_stats, detect_sweep, ema, ema_slope)


@dataclass
class SetupContext:
    tick: Tick
    bars: dict[str, list[Candle]]        # closed bars per timeframe
    features: dict[str, float]           # MarketIntelligenceAgent features (legacy setups use them)
    regime: str
    _cache: dict = field(default_factory=dict)

    def tf(self, name: str) -> list[Candle]:
        return self.bars.get(name, [])

    def closes(self, name: str) -> list[float]:
        key = ("closes", name)
        if key not in self._cache:
            self._cache[key] = [b.close for b in self.tf(name)]
        return self._cache[key]

    def atr(self, name: str) -> float:
        key = ("atr", name)
        if key not in self._cache:
            self._cache[key] = atr(self.tf(name))
        return self._cache[key]

    def adx(self, name: str) -> dict | None:
        key = ("adx", name)
        if key not in self._cache:
            self._cache[key] = adx(self.tf(name)[-80:])
        return self._cache[key]


@dataclass(frozen=True)
class SetupSignal:
    setup: str
    side: Side
    stop: float              # structural stop price
    reason: str
    evidence: dict


class Setup:
    """Base class. Subclasses set `name`, `family`, `regime` and implement `evaluate`."""

    name = "base"
    family = ""
    regime = ""

    def params(self) -> dict:
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}

    def evaluate(self, ctx: SetupContext) -> SetupSignal | None:  # pragma: no cover - interface
        raise NotImplementedError


def _bull(b: Candle) -> bool:
    return b.close > b.open


def _bear(b: Candle) -> bool:
    return b.close < b.open


class TrendPullback(Setup):
    """Trend filter on M15 (EMA slope + ADX), pullback to the M5 EMA, M1 close back in the trend direction."""

    name, family, regime = "trend_pullback", "trend continuation", "trending"

    def __init__(self, ema_fast: int = 20, ema_slow: int = 50, adx_min: float = 20.0, touch_atr: float = 0.3,
                 stop_lookback: int = 10, stop_buffer_atr: float = 0.1):
        self.ema_fast, self.ema_slow, self.adx_min = ema_fast, ema_slow, adx_min
        self.touch_atr, self.stop_lookback, self.stop_buffer_atr = touch_atr, stop_lookback, stop_buffer_atr

    def evaluate(self, ctx: SetupContext) -> SetupSignal | None:
        m1, a5 = ctx.tf("M1"), ctx.atr("M5")
        slope = ema_slope(ctx.closes("M15"), self.ema_slow, 5)
        d = ctx.adx("M15")
        e5 = ema(ctx.closes("M5"), self.ema_fast)
        if slope is None or d is None or e5 is None or a5 <= 0 or len(m1) < self.stop_lookback:
            return None
        if d["adx"] < self.adx_min:
            return None
        last, recent = m1[-1], m1[-self.stop_lookback:]
        ev = {"adx_m15": round(d["adx"], 1), "ema_slope_m15_atr": round(slope / a5, 3),
              "ema_m5": round(e5, 2)}
        if slope > 0 and d["plus_di"] > d["minus_di"]:
            touched = min(b.low for b in m1[-5:]) <= e5 + self.touch_atr * a5
            if touched and _bull(last) and last.close > e5:
                stop = min(b.low for b in recent) - self.stop_buffer_atr * a5
                return SetupSignal(self.name, Side.BUY, stop, "uptrend pullback to M5 EMA, M1 closed back up", ev)
        if slope < 0 and d["minus_di"] > d["plus_di"]:
            touched = max(b.high for b in m1[-5:]) >= e5 - self.touch_atr * a5
            if touched and _bear(last) and last.close < e5:
                stop = max(b.high for b in recent) + self.stop_buffer_atr * a5
                return SetupSignal(self.name, Side.SELL, stop, "downtrend pullback to M5 EMA, M1 closed back down", ev)
        return None


class Breakout(Setup):
    """Compression (low Bollinger bandwidth percentile on M5), then a fresh M1 close outside the last hour's
    range. Stop inside the range at `stop_frac` of its height."""

    name, family, regime = "breakout", "breakout", "breakout"

    def __init__(self, range_m1: int = 60, max_bw_pctile: float = 0.3, buffer_atr: float = 0.1,
                 stop_frac: float = 0.5):
        self.range_m1, self.max_bw_pctile, self.buffer_atr, self.stop_frac = range_m1, max_bw_pctile, buffer_atr, stop_frac

    def evaluate(self, ctx: SetupContext) -> SetupSignal | None:
        m1, a5 = ctx.tf("M1"), ctx.atr("M5")
        if len(m1) < self.range_m1 + 2 or a5 <= 0:
            return None
        bb = bollinger_stats(ctx.closes("M5"))
        if bb is None or bb["bandwidth_pctile"] is None or bb["bandwidth_pctile"] > self.max_bw_pctile:
            return None
        box = m1[-self.range_m1 - 2:-2]
        hi, lo = max(b.high for b in box), min(b.low for b in box)
        prev, last = m1[-2], m1[-1]
        buf = self.buffer_atr * a5
        ev = {"box_high": hi, "box_low": lo, "bw_pctile": round(bb["bandwidth_pctile"], 2)}
        if last.close > hi + buf and prev.close <= hi:
            return SetupSignal(self.name, Side.BUY, hi - self.stop_frac * (hi - lo), "compression breakout up", ev)
        if last.close < lo - buf and prev.close >= lo:
            return SetupSignal(self.name, Side.SELL, lo + self.stop_frac * (hi - lo), "compression breakout down", ev)
        return None


class FailedBreakout(Setup):
    """Price pierced the last hour's range within the last `k` M1 bars and the last bar closed back inside."""

    name, family, regime = "failed_breakout", "failed breakout", "ranging"

    def __init__(self, range_m1: int = 60, k: int = 3, min_pierce_atr: float = 0.1, stop_buffer_atr: float = 0.1):
        self.range_m1, self.k, self.min_pierce_atr, self.stop_buffer_atr = range_m1, k, min_pierce_atr, stop_buffer_atr

    def evaluate(self, ctx: SetupContext) -> SetupSignal | None:
        m1, a5 = ctx.tf("M1"), ctx.atr("M5")
        if len(m1) < self.range_m1 + self.k + 1 or a5 <= 0:
            return None
        box = m1[-self.range_m1 - self.k:-self.k]
        hi, lo = max(b.high for b in box), min(b.low for b in box)
        recent, last = m1[-self.k:], m1[-1]
        top, bottom = max(b.high for b in recent), min(b.low for b in recent)
        ev = {"box_high": hi, "box_low": lo}
        if top > hi + self.min_pierce_atr * a5 and last.close < hi and _bear(last):
            return SetupSignal(self.name, Side.SELL, top + self.stop_buffer_atr * a5,
                               "failed breakout above range, closed back inside", {**ev, "pierce": top})
        if bottom < lo - self.min_pierce_atr * a5 and last.close > lo and _bull(last):
            return SetupSignal(self.name, Side.BUY, bottom - self.stop_buffer_atr * a5,
                               "failed breakdown below range, closed back inside", {**ev, "pierce": bottom})
        return None


class RangeReversion(Setup):
    """Range regime (M15 ADX below `adx_max`); price traded outside the M5 Bollinger band in the last bars and
    the last M1 bar closed back inside, in the reversal direction."""

    name, family, regime = "range_reversion", "range mean reversion", "ranging"

    def __init__(self, adx_max: float = 20.0, bb_n: int = 20, bb_k: float = 2.0, lookback: int = 3,
                 stop_buffer_atr: float = 0.1):
        self.adx_max, self.bb_n, self.bb_k, self.lookback, self.stop_buffer_atr = adx_max, bb_n, bb_k, lookback, stop_buffer_atr

    def evaluate(self, ctx: SetupContext) -> SetupSignal | None:
        m1, a5 = ctx.tf("M1"), ctx.atr("M5")
        d = ctx.adx("M15")
        bb = bollinger(ctx.closes("M5"), self.bb_n, self.bb_k)
        if d is None or bb is None or a5 <= 0 or len(m1) < self.lookback + 1 or d["adx"] >= self.adx_max:
            return None
        recent, last = m1[-self.lookback:], m1[-1]
        ev = {"adx_m15": round(d["adx"], 1), "bb_upper": round(bb["upper"], 2), "bb_lower": round(bb["lower"], 2)}
        low = min(b.low for b in recent)
        high = max(b.high for b in recent)
        if low < bb["lower"] and last.close > bb["lower"] and _bull(last):
            return SetupSignal(self.name, Side.BUY, low - self.stop_buffer_atr * a5,
                               "range: below lower band and closed back inside", ev)
        if high > bb["upper"] and last.close < bb["upper"] and _bear(last):
            return SetupSignal(self.name, Side.SELL, high + self.stop_buffer_atr * a5,
                               "range: above upper band and closed back inside", ev)
        return None


class LiquiditySweep(Setup):
    """M1 wick beyond a confirmed swing (fractal) that had not been taken out, closing back inside it."""

    name, family, regime = "liquidity_sweep", "liquidity sweep / market structure", "any"

    def __init__(self, left: int = 5, right: int = 5, max_age: int = 120, min_wick_atr: float = 0.15,
                 stop_buffer_atr: float = 0.1):
        self.left, self.right, self.max_age = left, right, max_age
        self.min_wick_atr, self.stop_buffer_atr = min_wick_atr, stop_buffer_atr

    def evaluate(self, ctx: SetupContext) -> SetupSignal | None:
        m1, a5 = ctx.tf("M1"), ctx.atr("M5")
        if a5 <= 0:
            return None
        sw = detect_sweep(m1[-(self.max_age + self.left + self.right + 2):], self.left, self.right, self.max_age)
        if sw is None or abs(sw.extreme - sw.level) < self.min_wick_atr * a5:
            return None
        side = Side.BUY if sw.side == "BUY" else Side.SELL
        stop = sw.extreme - self.stop_buffer_atr * a5 if side == Side.BUY else sw.extreme + self.stop_buffer_atr * a5
        what = "lows" if side == Side.BUY else "highs"
        return SetupSignal(self.name, side, stop, f"liquidity sweep of swing {what} at {sw.level:.2f}",
                           {"swept_level": sw.level, "wick_extreme": sw.extreme, "swing_time": sw.swing_time.isoformat()})


class LegacyMomentum(Setup):
    """The incumbent's momentum-continuation candidate, kept for comparison (ATR stop)."""

    name, family, regime = "legacy_momentum", "momentum continuation (incumbent)", "trending"

    def __init__(self, threshold: float = 0.3, sl_atr_mult: float = 1.5):
        self.threshold, self.sl_atr_mult = threshold, sl_atr_mult

    def evaluate(self, ctx: SetupContext) -> SetupSignal | None:
        f, a5 = ctx.features, ctx.atr("M5")
        if not f or a5 <= 0:
            return None
        m = f["mom_m5_3"] + 0.5 * f["mom_m1_5"]
        d = self.sl_atr_mult * a5
        if m > self.threshold and f["tick_velocity"] > 0:
            return SetupSignal(self.name, Side.BUY, ctx.tick.ask - d, f"momentum continuation (m={m:.2f})", {"m": m})
        if m < -self.threshold and f["tick_velocity"] < 0:
            return SetupSignal(self.name, Side.SELL, ctx.tick.bid + d, f"momentum continuation (m={m:.2f})", {"m": m})
        return None


class LegacyRejection(Setup):
    """The incumbent's support/resistance wick-rejection candidate (ATR stop)."""

    name, family, regime = "legacy_rejection", "S/R rejection (incumbent)", "ranging"

    def __init__(self, distance_atr: float = 0.5, sl_atr_mult: float = 1.5):
        self.distance_atr, self.sl_atr_mult = distance_atr, sl_atr_mult

    def evaluate(self, ctx: SetupContext) -> SetupSignal | None:
        f, a5 = ctx.features, ctx.atr("M5")
        if not f or a5 <= 0:
            return None
        d = self.sl_atr_mult * a5
        if f["dist_sup_atr"] < self.distance_atr and f["wick_bias_m1"] > 0.2:
            return SetupSignal(self.name, Side.BUY, ctx.tick.ask - d, "rejection near support", {})
        if f["dist_res_atr"] < self.distance_atr and f["wick_bias_m1"] < -0.2:
            return SetupSignal(self.name, Side.SELL, ctx.tick.bid + d, "rejection near resistance", {})
        return None


class RandomBaseline(Setup):
    """Random side at a fixed per-bar probability with an ATR stop. The bar every setup must clear: if a setup
    cannot beat random timing with the same bracket and costs, its signal adds nothing."""

    name, family, regime = "random_baseline", "baseline", "any"

    def __init__(self, probability: float = 0.05, sl_atr: float = 1.0, seed: int = 0):
        self.probability, self.sl_atr, self.seed = probability, sl_atr, seed
        self._rng = random.Random(seed)

    def evaluate(self, ctx: SetupContext) -> SetupSignal | None:
        a5 = ctx.atr("M5")
        if a5 <= 0 or self._rng.random() >= self.probability:
            return None
        side = Side.BUY if self._rng.random() < 0.5 else Side.SELL
        d = self.sl_atr * a5
        stop = ctx.tick.ask - d if side == Side.BUY else ctx.tick.bid + d
        return SetupSignal(self.name, side, stop, "random entry (baseline)", {})


SETUPS: dict[str, type[Setup]] = {c.name: c for c in (
    TrendPullback, Breakout, FailedBreakout, RangeReversion, LiquiditySweep, LegacyMomentum, LegacyRejection,
    RandomBaseline)}
RESEARCH_SETUPS = ("trend_pullback", "breakout", "failed_breakout", "range_reversion", "liquidity_sweep",
                   "legacy_momentum", "legacy_rejection")


def make_setup(name: str, **params) -> Setup:
    if name not in SETUPS:
        raise ValueError(f"unknown setup {name!r}; known: {', '.join(SETUPS)}")
    return SETUPS[name](**params)

