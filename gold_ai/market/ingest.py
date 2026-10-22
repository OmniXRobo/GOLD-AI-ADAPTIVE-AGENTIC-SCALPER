"""Historical tick ingestion and market-data validation.

Supported inputs:
- MT5 "Export ticks" files (Symbols -> Ticks -> Export): tab-separated with header
  <DATE> <TIME> <BID> <ASK> <LAST> <VOLUME> <FLAGS>; rows may omit bid or ask when
  only one side changed, so the previous value is carried forward.
- Generic CSV with columns time,bid,ask[,volume] (ISO-8601 or epoch milliseconds).
Times are interpreted as UTC unless `tz_offset_hours` is given (MT5 exports use
broker server time, commonly UTC+2/+3).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from ..domain import Tick


@dataclass
class QualityReport:
    rows: int = 0
    accepted: int = 0
    dropped_nonpositive: int = 0
    dropped_crossed: int = 0
    dropped_out_of_order: int = 0
    dropped_spikes: int = 0
    gaps_over_threshold: int = 0
    max_gap_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def acceptance_rate(self) -> float:
        return self.accepted / self.rows if self.rows else 0.0


def _parse_mt5_time(d: str, t: str) -> datetime:
    fmt = "%Y.%m.%d %H:%M:%S.%f" if "." in t else "%Y.%m.%d %H:%M:%S"
    return datetime.strptime(f"{d} {t}", fmt)


def read_mt5_export(path: str | Path, tz_offset_hours: float = 0.0) -> Iterator[tuple[datetime, float, float, float]]:
    off = timedelta(hours=tz_offset_hours)
    bid = ask = 0.0
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.reader(f, delimiter="\t")
        header = [h.strip("<>").upper() for h in next(r)]
        ix = {h: i for i, h in enumerate(header)}
        for row in r:
            if not row:
                continue
            ts = _parse_mt5_time(row[ix["DATE"]], row[ix["TIME"]]) - off
            b = row[ix["BID"]].strip() if "BID" in ix else ""
            a = row[ix["ASK"]].strip() if "ASK" in ix else ""
            if b:
                bid = float(b)
            if a:
                ask = float(a)
            vol = row[ix["VOLUME"]].strip() if "VOLUME" in ix and len(row) > ix["VOLUME"] else ""
            yield ts.replace(tzinfo=timezone.utc), bid, ask, float(vol) if vol else 0.0


def read_generic_csv(path: str | Path, tz_offset_hours: float = 0.0) -> Iterator[tuple[datetime, float, float, float]]:
    off = timedelta(hours=tz_offset_hours)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            raw = row["time"].strip()
            if raw.isdigit():
                ts = datetime.fromtimestamp(int(raw) / 1000.0, tz=timezone.utc)
            else:
                ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            yield ts - off, float(row["bid"]), float(row["ask"]), float(row.get("volume") or 0)


def validate_ticks(rows: Iterable[tuple[datetime, float, float, float]], *, spike_pct: float = 1.0,
                   gap_seconds: float = 300.0, report: QualityReport | None = None) -> Iterator[Tick]:
    """Yield clean ticks. A spike is a mid move > spike_pct % from the previous accepted tick
    that is reverted by the next row; isolated large moves are kept (real gaps happen)."""
    rep = report if report is not None else QualityReport()
    prev: Tick | None = None
    held: Tick | None = None
    for ts, bid, ask, vol in rows:
        rep.rows += 1
        if bid <= 0 or ask <= 0:
            rep.dropped_nonpositive += 1
            continue
        if ask < bid:
            rep.dropped_crossed += 1
            continue
        t = Tick(ts, bid, ask, vol)
        if prev is not None and ts < prev.time:
            rep.dropped_out_of_order += 1
            continue
        if held is not None:
            # held tick was a big jump; keep it only if the market stayed there
            if abs(t.mid - held.mid) / held.mid * 100 > spike_pct and abs(t.mid - prev.mid) / prev.mid * 100 < spike_pct:
                rep.dropped_spikes += 1
            else:
                rep.accepted += 1
                yield held
                prev = held
            held = None
        if prev is not None:
            gap = (ts - prev.time).total_seconds()
            if gap > gap_seconds:
                rep.gaps_over_threshold += 1
            rep.max_gap_seconds = max(rep.max_gap_seconds, gap)
            if abs(t.mid - prev.mid) / prev.mid * 100 > spike_pct:
                held = t
                continue
        rep.accepted += 1
        prev = t
        yield t
    if held is not None:
        rep.accepted += 1
        yield held


def load_tick_file(path: str | Path, fmt: str = "auto", tz_offset_hours: float = 0.0,
                   report: QualityReport | None = None) -> list[Tick]:
    p = Path(path)
    if fmt == "auto":
        first = p.read_text(encoding="utf-8-sig", errors="ignore").split("\n", 1)[0]
        fmt = "mt5" if "<DATE>" in first.upper() else "csv"
    rows = read_mt5_export(p, tz_offset_hours) if fmt == "mt5" else read_generic_csv(p, tz_offset_hours)
    return list(validate_ticks(rows, report=report))
