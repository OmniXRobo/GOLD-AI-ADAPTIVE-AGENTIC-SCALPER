"""Compressed archive of old ticks: one gzip CSV per broker, symbol and UTC day.

The live database keeps the most recent `tick_retention_days`; older days are written here, verified by reading
them back, and only then deleted from the database. `MemoryStore.load_ticks` reads archived days transparently, so
research and backtests still see the full history. Nothing is ever deleted from the archive.
"""
from __future__ import annotations

import csv
import gzip
import io
import logging
import os
import threading
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from ..domain import Tick

log = logging.getLogger(__name__)

_FIELDS = ("time", "bid", "ask", "volume", "source")


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time(0), tzinfo=timezone.utc)


class TickArchive:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._ranges: dict[tuple[str, str], tuple[datetime, datetime] | None] = {}

    def _dir(self, broker: str, symbol: str) -> Path:
        return self.root / broker / symbol

    def path(self, broker: str, symbol: str, day: date) -> Path:
        return self._dir(broker, symbol) / f"{day.isoformat()}.csv.gz"

    def days(self, broker: str, symbol: str) -> list[date]:
        d = self._dir(broker, symbol)
        if not d.is_dir():
            return []
        out = []
        for p in d.glob("*.csv.gz"):
            try:
                out.append(date.fromisoformat(p.name.removesuffix(".csv.gz")))
            except ValueError:
                continue
        return sorted(out)

    def read_day(self, broker: str, symbol: str, day: date, source: str | None = None) -> list[Tick]:
        p = self.path(broker, symbol, day)
        if not p.exists():
            return []
        out = []
        with gzip.open(p, "rt", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if source and row["source"] != source:
                    continue
                out.append(Tick(datetime.fromisoformat(row["time"]), float(row["bid"]), float(row["ask"]),
                                float(row["volume"])))
        return out

    def read(self, broker: str, symbol: str, start: datetime | None = None, end: datetime | None = None,
             source: str | None = None) -> list[Tick]:
        out: list[Tick] = []
        for d in self.days(broker, symbol):
            if start and _day_start(d + timedelta(days=1)) <= start:
                continue
            if end and _day_start(d) >= end:
                break
            for t in self.read_day(broker, symbol, d, source):
                if (start is None or t.time >= start) and (end is None or t.time < end):
                    out.append(t)
        return out

    def range(self, broker: str, symbol: str) -> tuple[datetime, datetime] | None:
        if (broker, symbol) not in self._ranges:
            self._ranges[(broker, symbol)] = self._range(broker, symbol)
        return self._ranges[(broker, symbol)]

    def _range(self, broker: str, symbol: str) -> tuple[datetime, datetime] | None:
        days = self.days(broker, symbol)
        first = next((ts for d in days for ts in [self.read_day(broker, symbol, d)] if ts), None)
        last = next((ts for d in reversed(days) for ts in [self.read_day(broker, symbol, d)] if ts), None)
        return (first[0].time, last[-1].time) if first and last else None

    def write_day(self, broker: str, symbol: str, day: date, rows: list[tuple[Tick, str]]) -> int:
        """Writes (or extends) one day's file atomically and returns the number of ticks now in it, after
        reading the file back. Ticks already in the file (same time, bid and ask) are not written twice."""
        p = self.path(broker, symbol, day)
        p.parent.mkdir(parents=True, exist_ok=True)
        existing: list[tuple[Tick, str]] = []
        if p.exists():
            with gzip.open(p, "rt", newline="", encoding="utf-8") as f:
                existing = [(Tick(datetime.fromisoformat(r["time"]), float(r["bid"]), float(r["ask"]),
                                  float(r["volume"])), r["source"]) for r in csv.DictReader(f)]
        seen = {(t.time, t.bid, t.ask) for t, _ in existing}
        merged = existing + [(t, s) for t, s in rows if (t.time, t.bid, t.ask) not in seen]
        merged.sort(key=lambda ts: ts[0].time)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(_FIELDS)
        for t, s in merged:
            w.writerow((t.time.astimezone(timezone.utc).isoformat(), repr(t.bid), repr(t.ask), repr(t.volume), s))
        tmp = p.with_name(p.name + ".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
            f.write(buf.getvalue())
        with gzip.open(tmp, "rt", newline="", encoding="utf-8") as f:
            n = sum(1 for _ in csv.DictReader(f))
        if n != len(merged):
            tmp.unlink(missing_ok=True)
            raise OSError(f"archive verify failed for {p}: wrote {len(merged)} ticks, read back {n}")
        os.replace(tmp, p)
        self._ranges.pop((broker, symbol), None)
        return n


def archive_old_ticks(store, archive: TickArchive, older_than: datetime,
                      stop: threading.Event | None = None) -> dict[str, int]:
    """Moves every stored tick before the UTC day of `older_than` into the archive, one broker/symbol/day at a
    time: write + verify the file, then delete those rows. Returns ticks archived per 'broker:symbol'."""
    cutoff_day = older_than.astimezone(timezone.utc).date()
    cutoff = _day_start(cutoff_day)
    done: dict[str, int] = {}
    for broker, symbol in store.tick_pairs():
        key = f"{broker}:{symbol}"
        while not (stop and stop.is_set()):
            first = store.first_db_tick_time(broker, symbol)
            if first is None or first >= cutoff:
                break
            day = first.astimezone(timezone.utc).date()
            lo, hi = _day_start(day), _day_start(day + timedelta(days=1))
            rows = store.load_tick_rows(broker, symbol, lo, hi)          # [(id, Tick, source)]
            archive.write_day(broker, symbol, day, [(t, s) for _, t, s in rows])
            deleted = store.delete_tick_ids([i for i, _, _ in rows])     # only the rows just archived
            done[key] = done.get(key, 0) + deleted
            log.info("tick archive: %s %s %s -> %d ticks archived", broker, symbol, day, deleted)
    return done
