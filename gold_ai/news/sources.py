"""Calendar data adapters.

No provider is hardcoded and nothing here scrapes websites: the owner either
exports a calendar file from a provider they are licensed to use, or points the
generic HTTP JSON adapter at an API whose terms permit programmatic access.

Calendar file format (CSV with a header row, or JSON list of objects / {"events": [...]}):

    time      required  ISO-8601 timestamp (naive = UTC, "Z" accepted) or unix epoch.
                        Alternatively separate `date` (YYYY-MM-DD) and `time` (HH:MM) columns, UTC.
    title     required  event name as published, e.g. "Core CPI m/m"
    currency  optional  ISO code, default USD
    impact    optional  high/medium/low (also 1-3, red/orange/yellow)
    forecast, previous, actual   optional  numbers; "0.3%", "250K" accepted
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

from .events import EconomicEvent, normalize_impact, parse_number, parse_time


@runtime_checkable
class NewsSource(Protocol):
    name: str

    def fetch(self, start: datetime, end: datetime) -> list[EconomicEvent]:
        """Events with start <= time < end."""
        ...


def _event_from_record(rec: dict[str, Any], source: str) -> EconomicEvent:
    lower = {str(k).strip().lower(): v for k, v in rec.items()}
    if "date" in lower and lower.get("time") and ":" in str(lower["time"]) and "T" not in str(lower["time"]):
        t = parse_time(f"{lower['date']}T{lower['time']}")
    else:
        t = parse_time(lower.get("time") or lower.get("datetime") or lower["date"])
    title = str(lower.get("title") or lower.get("event") or "").strip()
    if not title:
        raise ValueError("calendar row without title")
    return EconomicEvent(
        time=t, title=title, currency=str(lower.get("currency") or "USD").strip().upper(),
        impact=normalize_impact(lower.get("impact")), forecast=parse_number(lower.get("forecast")),
        previous=parse_number(lower.get("previous")), actual=parse_number(lower.get("actual")), source=source,
    )


@dataclass
class CalendarFileSource:
    """Reads an owner-exported calendar file (.csv or .json). Re-read on every fetch."""

    path: str | Path
    name: str = "calendar_file"
    skipped_rows: int = 0

    def _records(self) -> list[dict]:
        p = Path(self.path)
        if p.suffix.lower() == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
            return data["events"] if isinstance(data, dict) else data
        with p.open(newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))

    def fetch(self, start: datetime, end: datetime) -> list[EconomicEvent]:
        out, self.skipped_rows = [], 0
        for rec in self._records():
            try:
                ev = _event_from_record(rec, self.name)
            except (KeyError, ValueError):
                self.skipped_rows += 1
                continue
            if start <= ev.time < end:
                out.append(ev)
        return sorted(out, key=lambda e: e.time)


@dataclass
class FieldMapping:
    """Where each EconomicEvent field lives in a provider's JSON item (dotted paths allowed)."""

    time: str = "time"
    title: str = "title"
    currency: str | None = "currency"
    impact: str | None = "impact"
    forecast: str | None = "forecast"
    previous: str | None = "previous"
    actual: str | None = "actual"


def _dig(obj: Any, path: str | None) -> Any:
    if not path:
        return obj
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


@dataclass
class HttpJsonSource:
    """Generic JSON calendar API adapter. The provider, URL, auth header and field mapping are configuration."""

    url: str
    mapping: FieldMapping = field(default_factory=FieldMapping)
    items_path: str | None = None            # dotted path to the list of events in the response
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    start_param: str | None = None           # query param names for the window, if the API supports it
    end_param: str | None = None
    param_time_format: str = "%Y-%m-%d"
    timeout: float = 10.0
    client: httpx.Client | None = None
    name: str = "http_json"
    skipped_items: int = 0

    def fetch(self, start: datetime, end: datetime) -> list[EconomicEvent]:
        params = dict(self.params)
        if self.start_param:
            params[self.start_param] = start.strftime(self.param_time_format)
        if self.end_param:
            params[self.end_param] = end.strftime(self.param_time_format)
        client = self.client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.get(self.url, params=params, headers=self.headers)
            resp.raise_for_status()
            items = _dig(resp.json(), self.items_path) or []
        finally:
            if self.client is None:
                client.close()
        m, out, self.skipped_items = self.mapping, [], 0
        for it in items:
            rec = {"time": _dig(it, m.time), "title": _dig(it, m.title)}
            for k in ("currency", "impact", "forecast", "previous", "actual"):
                path = getattr(m, k)
                rec[k] = _dig(it, path) if path else None
            try:
                ev = _event_from_record(rec, self.name)
            except (KeyError, ValueError, TypeError):
                self.skipped_items += 1
                continue
            if start <= ev.time < end:
                out.append(ev)
        return sorted(out, key=lambda e: e.time)
