"""Read-only MT5 market-data collector: copies broker ticks into persistent storage.

Resumes from the last stored tick per (broker, symbol) after a restart, so no
range is fetched twice and gaps are filled up to the broker's tick history.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from .brokers.mt5_connector import MT5ReadOnlyConnector
from .memory.store import MemoryStore

log = logging.getLogger(__name__)


class TickCollector:
    def __init__(self, connector: MT5ReadOnlyConnector, store: MemoryStore, broker: str, symbol: str,
                 interval_seconds: float = 5.0, backfill: timedelta = timedelta(hours=1)):
        self.c, self.store, self.broker, self.symbol = connector, store, broker, symbol
        self.interval = interval_seconds
        self.backfill = backfill
        self._stop = threading.Event()
        self.collected = 0
        self.errors = 0

    def _cursor_key(self) -> str:
        return f"collector:{self.broker}:{self.symbol}:last"

    def collect_once(self, now: datetime | None = None) -> int:
        if not getattr(self.c, "server_offset_known", True):
            self.c.latest_tick(self.symbol)   # measures the broker's server-time offset from live ticks
            if not self.c.server_offset_known:
                return 0
        now = now or datetime.now(timezone.utc)
        last =self.store.kv_get(self._cursor_key())
        start = datetime.fromisoformat(last) + timedelta(milliseconds=1) if last else now - self.backfill
        ticks = self.c.ticks_range(self.symbol, start, now)
        if not ticks:
            return 0
        n = self.store.save_ticks(self.broker, self.symbol, ticks, source="mt5")
        self.store.kv_set(self._cursor_key(), ticks[-1].time.isoformat())
        self.collected += n
        return n

    def run(self, stop: threading.Event | None = None) -> None:
        """Collect until `stop()` is called or the given (supervisor) stop event is set."""
        def stopped() -> bool:
            return self._stop.is_set() or (stop is not None and stop.is_set())

        while not stopped():
            try:
                self.collect_once()
            except Exception:
                self.errors += 1
                log.exception("tick collection failed")
            (stop or self._stop).wait(self.interval)

    def stop(self) -> None:
        self._stop.set()


def backfill_history(connector, store: MemoryStore, broker: str, symbol: str, start: datetime,
                     end: datetime | None = None, chunk: timedelta = timedelta(hours=6)) -> int:
    """Copy the broker's stored tick history for [start, end) into storage, read-only.

    `end` defaults to the earliest tick already stored for this broker/symbol, so the live
    collector's range is never duplicated. The connector converts broker server time to UTC with
    its current offset; a range spanning a daylight-saving switch is shifted by an hour on one side.
    """
    if end is None:
        end = store.first_tick_time(broker, symbol) or datetime.now(timezone.utc)
    total, t = 0, start
    while t < end:
        stop = min(t + chunk, end)
        ticks = [x for x in connector.ticks_range(symbol, t, stop) if x.time < stop]
        if ticks:
            total += store.save_ticks(broker, symbol, ticks, source="mt5_history")
        log.info("backfill %s %s .. %s: %d ticks", symbol, t.isoformat(), stop.isoformat(), len(ticks))
        t = stop
    return total
