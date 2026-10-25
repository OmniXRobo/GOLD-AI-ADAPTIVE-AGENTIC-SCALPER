"""Re-iterable tick streams for research, so weeks of stored ticks are read a chunk at a time instead of being
held in memory (a list of 20M ticks needs several GB)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Callable, Iterable, Iterator

from ..domain import Tick


class TickStream:
    def __init__(self, factory: Callable[[], Iterable[Tick]], start: datetime, end: datetime):
        self.factory, self.start, self.end = factory, start, end

    @classmethod
    def from_list(cls, ticks: list[Tick]) -> "TickStream":
        if not ticks:
            raise ValueError("no ticks supplied")
        return cls(lambda: ticks, ticks[0].time, ticks[-1].time)

    @classmethod
    def from_store(cls, store, broker: str, symbol: str, start: datetime | None = None,
                   end: datetime | None = None) -> "TickStream | None":
        rng = store.tick_range(broker, symbol, start, end)
        if rng is None:
            return None
        a, z = rng
        return cls(lambda: store.iter_ticks(broker, symbol, a, z + timedelta(milliseconds=1)), a, z)

    def __iter__(self) -> Iterator[Tick]:
        prev = None
        for t in self.factory():
            if prev is not None and t.time < prev:
                raise ValueError("ticks must be time-ordered")
            prev = t.time
            yield t


class Meter:
    """Wraps one pass over a stream and records the tick count, M1 bar count and the data hash (same format
    as `engines.loop.data_hash`)."""

    def __init__(self, ticks: Iterable[Tick]):
        self._ticks = ticks
        self.count = 0
        self.m1_bars = 0
        self._h = hashlib.sha256()

    def __iter__(self) -> Iterator[Tick]:
        last_minute = None
        for t in self._ticks:
            self.count += 1
            m = int(t.time.timestamp()) // 60
            if m != last_minute:
                self.m1_bars += 1
                last_minute = m
            self._h.update(f"{t.time.isoformat()}|{t.bid}|{t.ask}\n".encode())
            yield t

    @property
    def data_hash(self) -> str:
        return self._h.hexdigest()[:32]
