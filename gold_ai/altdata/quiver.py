"""Quiver Quantitative alternative-data adapter (optional, read-only).

Quiver (api.quiverquant.com, paid API token) is equity-focused. The only datasets with a
plausible, indirect link to gold are used:

  * off-exchange (dark pool) short volume for gold ETFs, default GLD and IAU
  * congressional trades disclosed in gold ETFs and miners

Both are daily disclosures, not tick data. They are slow context for the virtual engine,
never a scalping trigger, and nothing here claims they improve results; that has to be
shown by recorded virtual trades.

No look-ahead: an off-exchange row dated D counts only from D + `offexchange_lag_days`,
and a congress trade only from its *report* (disclosure) date, not its transaction date.

Endpoint paths and field names are configuration because Quiver's public docs do not
publish a schema; check them against a live response once a token is configured.
Without a token the agent reports available=False and neutral values. It never fabricates data.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://api.quiverquant.com"


@dataclass(frozen=True)
class OffExchangeDay:
    date: datetime
    ticker: str
    short_volume: float
    total_volume: float

    @property
    def short_ratio(self) -> float | None:
        return self.short_volume / self.total_volume if self.total_volume > 0 else None


@dataclass(frozen=True)
class CongressTrade:
    report_date: datetime
    ticker: str
    side: str          # "buy" | "sell"
    member: str = ""


@dataclass
class QuiverConfig:
    offexchange_tickers: list[str] = field(default_factory=lambda: ["GLD", "IAU"])
    congress_tickers: list[str] = field(default_factory=lambda: ["GLD", "IAU", "GDX", "NEM"])
    offexchange_path: str = "/beta/historical/offexchange/{ticker}"
    congress_path: str = "/beta/historical/congresstrading/{ticker}"
    offexchange_lag_days: int = 1          # daily figures are usable the next day
    zscore_window_days: int = 60
    zscore_min_samples: int = 20
    congress_window_days: int = 30
    timeout: float = 15.0


def _date(v: Any) -> datetime:
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00")[:19])
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def _num(v: Any) -> float:
    return float(str(v).replace(",", ""))


def parse_offexchange(ticker: str, rows: list[dict]) -> list[OffExchangeDay]:
    out = []
    for r in rows or []:
        try:
            out.append(OffExchangeDay(_date(r["Date"]), ticker.upper(), _num(r["OTC_Short"]), _num(r["OTC_Total"])))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(out, key=lambda d: d.date)


def _side(txn: Any) -> str | None:
    t = str(txn or "").lower()
    if t.startswith("purchase") or t == "buy":
        return "buy"
    if t.startswith("sale") or t == "sell":
        return "sell"
    return None   # exchanges and unknown types are not counted


def parse_congress(ticker: str, rows: list[dict]) -> list[CongressTrade]:
    out = []
    for r in rows or []:
        side = _side(r.get("Transaction"))
        if side is None:
            continue
        try:
            out.append(CongressTrade(_date(r["ReportDate"]), ticker.upper(), side,
                                     str(r.get("Representative") or r.get("Name") or "")))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(out, key=lambda t: t.report_date)


class QuiverClient:
    def __init__(self, token: str, base_url: str = BASE_URL, timeout: float = 15.0,
                 client: httpx.Client | None = None):
        if not token:
            raise ValueError("Quiver API token required")
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self.base_url, self.timeout, self._client = base_url.rstrip("/"), timeout, client

    def get(self, path: str) -> list[dict]:
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.get(self.base_url + path, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._client is None:
                client.close()
        return data if isinstance(data, list) else []


NEUTRAL: dict[str, float] = {
    "alt_etf_offex_short_ratio": 0.5, "alt_etf_offex_short_z": 0.0,
    "alt_congress_gold_net_30d": 0.0, "alt_congress_gold_trades_30d": 0.0,
}


@dataclass
class QuiverFeatures:
    available: bool
    values: dict[str, float]
    sources: list[str] = field(default_factory=list)
    as_of: dict[str, str] = field(default_factory=dict)


class QuiverAgent:
    """Holds Quiver data pulled by a slow background job and turns it into context features."""

    def __init__(self, client: QuiverClient | None = None, cfg: QuiverConfig | None = None):
        self.client, self.cfg = client, cfg or QuiverConfig()
        self.offexchange: dict[str, list[OffExchangeDay]] = {}
        self.congress: dict[str, list[CongressTrade]] = {}
        self.source_errors: dict[str, str] = {}
        self.last_refresh: datetime | None = None

    @property
    def available(self) -> bool:
        return self.client is not None

    def refresh(self, now: datetime | None = None) -> int:
        """Pull every configured dataset; a failing request is recorded and skipped. Returns rows loaded."""
        if self.client is None:
            return 0
        c, n = self.cfg, 0
        jobs = [(f"offexchange:{t}", c.offexchange_path, t, parse_offexchange, self.offexchange)
                for t in c.offexchange_tickers]
        jobs += [(f"congress:{t}", c.congress_path, t, parse_congress, self.congress) for t in c.congress_tickers]
        for name, path, ticker, parse, store in jobs:
            try:
                rows = parse(ticker, self.client.get(path.format(ticker=ticker.upper())))
                store[ticker.upper()] = rows
                self.source_errors.pop(name, None)
                n += len(rows)
            except Exception as e:  # a provider outage must not stop the service
                code = getattr(getattr(e, "response", None), "status_code", None)
                self.source_errors[name] = f"{type(e).__name__}{f' {code}' if code else ''}"
                log.warning("quiver %s failed: %s", name, self.source_errors[name])
        self.last_refresh = now or datetime.now(timezone.utc)
        return n

    def _usable_offexchange(self, now: datetime) -> list[tuple[datetime, float]]:
        """Daily short ratio averaged over the configured ETFs, only days already public at `now`."""
        lag = timedelta(days=self.cfg.offexchange_lag_days)
        by_day: dict[datetime, list[float]] = {}
        for rows in self.offexchange.values():
            for d in rows:
                if d.date + lag <= now and (r := d.short_ratio) is not None:
                    by_day.setdefault(d.date, []).append(r)
        return [(day, sum(v) / len(v)) for day, v in sorted(by_day.items())]

    def features(self, now: datetime) -> QuiverFeatures:
        now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
        v = dict(NEUTRAL)
        avail = {"offex": 0.0, "congress": 0.0}
        as_of: dict[str, str] = {}
        if self.available:
            series = self._usable_offexchange(now)
            if series:
                last_day, last = series[-1]
                v["alt_etf_offex_short_ratio"], avail["offex"] = last, 1.0
                as_of["offexchange"] = last_day.date().isoformat()
                hist = [r for d, r in series if d > last_day - timedelta(days=self.cfg.zscore_window_days)]
                if len(hist) >= self.cfg.zscore_min_samples:
                    mean = sum(hist) / len(hist)
                    sd = math.sqrt(sum((x - mean) ** 2 for x in hist) / (len(hist) - 1))
                    v["alt_etf_offex_short_z"] = (last - mean) / sd if sd > 0 else 0.0
            if self.congress:
                start = now - timedelta(days=self.cfg.congress_window_days)
                recent = [t for rows in self.congress.values() for t in rows if start <= t.report_date <= now]
                v["alt_congress_gold_trades_30d"] = float(len(recent))
                v["alt_congress_gold_net_30d"] = float(sum(1 if t.side == "buy" else -1 for t in recent))
                avail["congress"] = 1.0
                public = [t.report_date for rows in self.congress.values() for t in rows if t.report_date <= now]
                if public:
                    as_of["congress"] = max(public).date().isoformat()
        v.update({f"alt_{k}_available": a for k, a in avail.items()})
        sources = [k for k, a in (("offexchange", avail["offex"]), ("congress", avail["congress"])) if a]
        return QuiverFeatures(self.available, v, sources, as_of)
