"""Read-only MT5 market-data collector: copies broker ticks into persistent storage.

Resumes from the last stored tick per (broker, symbol) after a restart, so no
range is fetched twice and gaps are filled up to the broker's tick history.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from .brokers.mt5_connector import MT5ReadOnlyConnector
from .memory.store import MemoryStore

log = logging.getLogger(__name__)


class TickCollector:
    def __init__(self, connector: MT5ReadOnlyConnector, store: MemoryStore, broker: str, symbol: str,
                 interval_seconds: float = 5.0, backfill: timedelta = timedelta(hours=1),
                 max_span: timedelta = timedelta(minutes=15)):
        self.c, self.store, self.broker, self.symbol = connector, store, broker, symbol
        self.interval = interval_seconds
        self.backfill = backfill
        # After a gap, catch up `max_span` of broker history per call (short reads, short write transactions),
        # looping without the poll wait until caught up, instead of copying and inserting hours at once.
        self.max_span = max_span
        self.behind = False
        self._stop = threading.Event()
        self.collected = 0
        self.errors = 0
        self.consecutive_errors = 0
        self.last_error: str | None = None
        self.last_success_at: datetime | None = None
        self.failing_since: datetime | None = None
        self._last_logged = 0.0

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
        end = min(now, start + self.max_span)
        self.behind = end < now
        ticks = self.c.ticks_range(self.symbol, start, end)
        if not ticks:
            if self.behind:   # an empty slice (market closed) still moves the cursor forward
                self.store.kv_set(self._cursor_key(), (end - timedelta(milliseconds=1)).isoformat())
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
            except Exception as e:
                self._on_error(e)
            else:
                if self.consecutive_errors:
                    log.warning("tick collection for %s resumed after %d failed attempts",
                                self.symbol, self.consecutive_errors)
                self.consecutive_errors = 0
                self.failing_since = None
                self.last_success_at = datetime.now(timezone.utc)
                if self.behind:
                    (stop or self._stop).wait(0.2)   # catching up: next slice soon, but yield to other writers
                    continue
            (stop or self._stop).wait(self.interval)

    def _on_error(self, e: Exception) -> None:
        """Full traceback for the first failure of a streak, then one line at most every 5 minutes, so a
        terminal outage does not fill the disk with identical tracebacks (it wrote 110 MB a day before)."""
        self.errors += 1
        self.consecutive_errors += 1
        self.last_error = f"{type(e).__name__}: {e}"
        now = time.monotonic()
        if self.consecutive_errors == 1:
            self.failing_since = datetime.now(timezone.utc)
            log.exception("tick collection failed for %s", self.symbol)
            self._last_logged = now
        elif now - self._last_logged >= 300:
            log.error("tick collection for %s still failing (%d attempts in a row): %s",
                      self.symbol, self.consecutive_errors, self.last_error)
            self._last_logged = now

    def status(self) -> dict:
        return {"symbol": self.symbol, "collected": self.collected, "errors": self.errors,
                "consecutive_errors": self.consecutive_errors, "last_error": self.last_error,
                "failing_since": self.failing_since.isoformat() if self.failing_since else None,
                "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None}

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
