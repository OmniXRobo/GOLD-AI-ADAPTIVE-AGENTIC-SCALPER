"""Tick -> candle aggregation for M1..D1, plus derived M10.

Candles are built from Bid prices (MT5 convention). Aggregation is strictly
causal: a bar is only emitted once a tick from a later bar arrives, so consumers
never see an incomplete bar as closed (prevents look-ahead bias).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..domain import Candle, Tick

TIMEFRAMES: dict[str, int] = {
    "M1": 60, "M5": 300, "M10": 600, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}


def bar_open(t: datetime, seconds: int) -> datetime:
    epoch = int(t.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=t.tzinfo)


class CandleBuilder:
    def __init__(self, timeframe: str):
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"unknown timeframe {timeframe}")
        self.timeframe = timeframe
        self.seconds = TIMEFRAMES[timeframe]
        self._cur: dict | None = None

    def update(self, tick: Tick) -> Candle | None:
        """Feed one tick; returns the previous bar when it closes."""
        start = bar_open(tick.time, self.seconds)
        price = tick.bid
        closed = None
        if self._cur is not None and start != self._cur["time"]:
            if start < self._cur["time"]:
                raise ValueError("ticks out of order")
            closed = self._finish()
        if self._cur is None:
            self._cur = {"time": start, "open": price, "high": price, "low": price,
                         "close": price, "n": 0, "spread_sum": 0.0}
        c = self._cur
        c["high"] = max(c["high"], price)
        c["low"] = min(c["low"], price)
        c["close"] = price
        c["n"] += 1
        c["spread_sum"] += tick.spread
        return closed

    def _finish(self) -> Candle:
        c = self._cur
        assert c is not None
        self._cur = None
        return Candle(c["time"], c["open"], c["high"], c["low"], c["close"], c["n"], c["spread_sum"] / c["n"])

    def flush(self) -> Candle | None:
        return self._finish() if self._cur else None


def build_candles(ticks: Iterable[Tick], timeframe: str, include_partial: bool = False) -> list[Candle]:
    b = CandleBuilder(timeframe)
    out = [c for t in ticks if (c := b.update(t)) is not None]
    if include_partial and (last := b.flush()):
        out.append(last)
    return out


def resample(candles: list[Candle], timeframe: str) -> list[Candle]:
    """Derive a higher timeframe (e.g. M10 from M1/M5). Input must be lower-TF bars."""
    secs = TIMEFRAMES[timeframe]
    out: list[Candle] = []
    group: list[Candle] = []
    for c in candles:
        if group and bar_open(c.time, secs) != bar_open(group[0].time, secs):
            out.append(_merge(group, secs))
            group = []
        group.append(c)
    if group:
        out.append(_merge(group, secs))
    return out


def _merge(group: list[Candle], secs: int) -> Candle:
    n = sum(c.tick_volume for c in group)
    sp = sum(c.spread_avg * c.tick_volume for c in group) / n if n else 0.0
    return Candle(bar_open(group[0].time, secs), group[0].open, max(c.high for c in group),
                  min(c.low for c in group), group[-1].close, n, sp)


class MultiTimeframeBuilder:
    def __init__(self, timeframes: Iterable[str] = ("M1", "M5", "M10", "M15", "M30", "H1", "H4", "D1"),
                 max_bars: int = 500):
        self.builders = {tf: CandleBuilder(tf) for tf in timeframes}
        self.bars: dict[str, list[Candle]] = {tf: [] for tf in timeframes}
        self.max_bars = max_bars

    def update(self, tick: Tick) -> dict[str, Candle]:
        closed = {}
        for tf, b in self.builders.items():
            c = b.update(tick)
            if c is not None:
                lst = self.bars[tf]
                lst.append(c)
                if len(lst) > self.max_bars:
                    del lst[: len(lst) - self.max_bars]
                closed[tf] = c
        return closed


    def seed(self, timeframe: str, candles: list[Candle], before: datetime) -> int:
        """Prepend closed broker bars that end at or before `before` (the first tick about to be replayed),
        so higher timeframes have history without waiting days for ticks. Returns the number added."""
        if timeframe not in self.bars:
            return 0
        secs = TIMEFRAMES[timeframe]
        have = self.bars[timeframe]
        first = have[0].time if have else None
        old = [c for c in candles if c.time.timestamp() + secs <= before.timestamp()
               and (first is None or c.time < first)]
        old.sort(key=lambda c: c.time)
        merged = old + have
        self.bars[timeframe] = merged[-self.max_bars:]
        return len(old)


__all__ = ["TIMEFRAMES", "CandleBuilder", "build_candles", "resample", "MultiTimeframeBuilder", "bar_open"]
