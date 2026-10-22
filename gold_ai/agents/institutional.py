"""Institutional Flow Intelligence Agent (optional).

Derives flow features from LICENSED external data the owner configures:
COMEX GC futures quotes / volume / open interest, order-book depth snapshots,
time-and-sales prints, and CFTC Commitments of Traders reports (user-supplied CSV).

Important: retail MT5 tick volume is NOT institutional order flow. XAUUSD on a
retail broker is an OTC CFD quote stream; its "volume" counts price updates at
that broker only. This agent never derives order-flow features from it. The only
spot-derived feature is the liquidity-sweep detector, which is pure price action
and is reported under its own availability flag.

When no data source is configured the agent reports available=False and returns
neutral values (0 for signed features, 0.5 for ratios/percentiles). It never
fabricates data. Every feature has a matching *_available flag (1.0 / 0.0).
"""
from __future__ import annotations

import csv
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from ..domain import Tick


# -- data types ------------------------------------------------------------------------
@dataclass(frozen=True)
class FuturesQuote:
    time: datetime
    symbol: str            # e.g. "GCZ6"
    bid: float
    ask: float
    last: float = 0.0
    volume: float = 0.0    # session volume
    open_interest: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True)
class BookSnapshot:
    time: datetime
    bids: tuple[tuple[float, float], ...]   # (price, size), best first
    asks: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class TradePrint:
    time: datetime
    price: float
    size: float
    aggressor: str | None = None   # "buy" | "sell" | None (then classified by tick rule)


@dataclass(frozen=True)
class CotRecord:
    report_date: datetime          # "as of" Tuesday
    managed_money_long: float
    managed_money_short: float
    open_interest: float = 0.0

    @property
    def net(self) -> float:
        return self.managed_money_long - self.managed_money_short


# -- adapter protocols (implement against your licensed vendor) -----------------------------
class FuturesQuoteSource(Protocol):
    def latest_quote(self) -> FuturesQuote | None: ...


class DepthSource(Protocol):
    def latest_book(self) -> BookSnapshot | None: ...


class TradePrintSource(Protocol):
    def prints_since(self, since: datetime) -> list[TradePrint]: ...


class CotSource(Protocol):
    def reports(self) -> list[CotRecord]: ...


@dataclass
class CotCsvSource:
    """CFTC COT CSV supplied by the user (disaggregated futures-only layout by default).

    Simple layouts with columns date, mm_long, mm_short[, open_interest] are also accepted.
    Rows are filtered to markets whose name contains `market_filter` when that column exists.
    """

    path: str | Path
    market_filter: str = "GOLD"
    date_col: str = "Report_Date_as_YYYY-MM-DD"
    long_col: str = "M_Money_Positions_Long_All"
    short_col: str = "M_Money_Positions_Short_All"
    oi_col: str = "Open_Interest_All"
    market_col: str = "Market_and_Exchange_Names"

    def reports(self) -> list[CotRecord]:
        out = []
        with Path(self.path).open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
                mkt = row.get(self.market_col)
                if mkt is not None and self.market_filter.upper() not in mkt.upper():
                    continue
                try:
                    d = row.get(self.date_col) or row["date"]
                    lng = row.get(self.long_col) or row["mm_long"]
                    sht = row.get(self.short_col) or row["mm_short"]
                    oi = row.get(self.oi_col) or row.get("open_interest") or 0
                    dt = datetime.fromisoformat(d[:10]).replace(tzinfo=timezone.utc)
                    out.append(CotRecord(dt, float(lng.replace(",", "")), float(sht.replace(",", "")),
                                         float(str(oi).replace(",", ""))))
                except (KeyError, ValueError):
                    continue
        return sorted(out, key=lambda r: r.report_date)


# -- agent -----------------------------------------------------------------------------------
@dataclass
class InstitutionalConfig:
    book_levels: int = 5
    print_window_seconds: float = 60.0
    basis_window: int = 500              # basis observations for the z-score
    basis_min_samples: int = 30
    oi_lookback_seconds: float = 3600.0
    cot_lookback_reports: int = 156      # ~3 years of weekly reports
    cot_release_lag_days: int = 3        # Tuesday data is published Friday: no look-ahead
    max_data_age_seconds: float = 30.0   # older quotes/books count as unavailable
    sweep_lookback_seconds: float = 300.0
    sweep_reversal_seconds: float = 30.0
    sweep_min_pierce: float = 0.05       # price units beyond the swing level


@dataclass
class InstitutionalFeatures:
    available: bool
    values: dict[str, float]
    sources: list[str] = field(default_factory=list)


NEUTRAL: dict[str, float] = {
    "inst_book_imbalance": 0.0, "inst_aggressive_buy_ratio": 0.5, "inst_basis": 0.0, "inst_basis_z": 0.0,
    "inst_oi_change": 0.0, "inst_oi_change_pct": 0.0, "inst_cot_mm_net_pct": 0.5,
    "spot_liquidity_sweep": 0.0, "spot_sweep_age_seconds": 0.0,
}
_AVAIL = ("book", "prints", "basis", "oi", "cot", "sweep")


def _sanitize(t: datetime) -> datetime:
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


class InstitutionalFlowAgent:
    def __init__(self, futures: FuturesQuoteSource | None = None, depth: DepthSource | None = None,
                 prints: TradePrintSource | None = None, cot: CotSource | None = None,
                 cfg: InstitutionalConfig | None = None, push_feed: bool = False):
        """push_feed=True: licensed data is pushed in via on_futures_quote / on_book / on_trade_print."""
        self.push_feed = push_feed
        self.futures, self.depth, self.prints_src, self.cot = futures, depth, prints, cot
        self.cfg = cfg or InstitutionalConfig()
        c = self.cfg
        self._spot: deque[Tick] = deque()
        self._quotes: deque[FuturesQuote] = deque()
        self._basis: deque[float] = deque(maxlen=c.basis_window)
        self._book: BookSnapshot | None = None
        self._prints: deque[TradePrint] = deque()
        self._last_print_price: float | None = None
        self._cot: list[CotRecord] = []
        self._last_poll: datetime | None = None
        self._last_sweep: tuple[datetime, float] | None = None

    @property
    def configured_sources(self) -> list[str]:
        return [n for n, s in (("futures", self.futures), ("depth", self.depth), ("prints", self.prints_src),
                               ("cot", self.cot)) if s is not None] + (["push"] if self.push_feed else [])

    @property
    def available(self) -> bool:
        return bool(self.configured_sources)

    # -- ingestion ---------------------------------------------------------------------
    def on_spot_tick(self, tick: Tick) -> None:
        self._spot.append(tick)
        horizon = tick.time - timedelta(seconds=self.cfg.sweep_lookback_seconds)
        while self._spot and self._spot[0].time < horizon:
            self._spot.popleft()
        self._detect_sweep(tick.time)

    def on_futures_quote(self, q: FuturesQuote) -> None:
        if self._quotes and q.time <= self._quotes[-1].time:
            return
        self._quotes.append(q)
        while self._quotes and self._quotes[0].time < q.time - timedelta(seconds=2 * self.cfg.oi_lookback_seconds):
            self._quotes.popleft()
        spot = self._spot[-1] if self._spot else None
        if spot is not None and abs((q.time - spot.time).total_seconds()) <= self.cfg.max_data_age_seconds:
            self._basis.append(q.mid - spot.mid)

    def on_book(self, book: BookSnapshot) -> None:
        self._book = book

    def on_trade_print(self, p: TradePrint) -> None:
        side = p.aggressor
        if side not in ("buy", "sell"):
            # tick rule: uptick = buyer-initiated, downtick = seller-initiated, zero tick = unknown
            prev = self._last_print_price
            side = None if prev is None or p.price == prev else ("buy" if p.price > prev else "sell")
        self._last_print_price = p.price
        if side:
            self._prints.append(TradePrint(p.time, p.price, p.size, side))

    def load_cot(self, records: list[CotRecord]) -> None:
        self._cot = sorted(records, key=lambda r: r.report_date)

    def poll(self, now: datetime) -> None:
        """Pull the latest data from every configured source."""
        if self.futures and (q := self.futures.latest_quote()) is not None:
            self.on_futures_quote(q)
        if self.depth and (b := self.depth.latest_book()) is not None:
            self.on_book(b)
        if self.prints_src:
            since = self._last_poll or now - timedelta(seconds=self.cfg.print_window_seconds)
            for p in sorted(self.prints_src.prints_since(since), key=lambda x: x.time):
                self.on_trade_print(p)
        if self.cot and not self._cot:
            self.load_cot(self.cot.reports())
        self._last_poll = now

    # -- feature computation ----------------------------------------------------------------
    def _fresh(self, t: datetime, now: datetime) -> bool:
        return 0 <= (now - t).total_seconds() <= self.cfg.max_data_age_seconds

    def book_imbalance(self, now: datetime) -> float | None:
        b = self._book
        if b is None or not self._fresh(b.time, now):
            return None
        n = self.cfg.book_levels
        bid, ask = sum(s for _, s in b.bids[:n]), sum(s for _, s in b.asks[:n])
        return (bid - ask) / (bid + ask) if bid + ask > 0 else None

    def aggressive_buy_ratio(self, now: datetime) -> float | None:
        cutoff = now - timedelta(seconds=self.cfg.print_window_seconds)
        while self._prints and self._prints[0].time < cutoff:
            self._prints.popleft()
        buy = sum(p.size for p in self._prints if p.aggressor == "buy" and p.time <= now)
        sell = sum(p.size for p in self._prints if p.aggressor == "sell" and p.time <= now)
        return buy / (buy + sell) if buy + sell > 0 else None

    def basis(self, now: datetime) -> tuple[float, float] | None:
        """(futures mid - spot mid, z-score vs recent basis history). Basis includes cost of carry."""
        if not self._quotes or not self._basis or not self._fresh(self._quotes[-1].time, now):
            return None
        b = self._basis[-1]
        hist = list(self._basis)
        if len(hist) < self.cfg.basis_min_samples:
            return b, 0.0
        mean = sum(hist) / len(hist)
        sd = math.sqrt(sum((x - mean) ** 2 for x in hist) / (len(hist) - 1))
        return b, (b - mean) / sd if sd > 0 else 0.0

    def oi_change(self, now: datetime) -> tuple[float, float] | None:
        if len(self._quotes) < 2 or not self._fresh(self._quotes[-1].time, now):
            return None
        last = self._quotes[-1]
        target = last.time - timedelta(seconds=self.cfg.oi_lookback_seconds)
        ref = next((q for q in reversed(self._quotes) if q.time <= target), self._quotes[0])
        if ref is last or ref.open_interest <= 0:
            return None
        d = last.open_interest - ref.open_interest
        return d, d / ref.open_interest * 100.0

    def cot_percentile(self, now: datetime) -> float | None:
        usable = [r for r in self._cot if r.report_date + timedelta(days=self.cfg.cot_release_lag_days) <= now]
        usable = usable[-self.cfg.cot_lookback_reports:]
        if len(usable) < 2:
            return None
        latest = usable[-1].net
        return sum(1 for r in usable if r.net <= latest) / len(usable)

    def _detect_sweep(self, now: datetime) -> None:
        c = self.cfg
        split = now - timedelta(seconds=c.sweep_reversal_seconds)
        older = [t.mid for t in self._spot if t.time < split]
        recent = [t.mid for t in self._spot if t.time >= split]
        if len(older) < 3 or len(recent) < 2:
            return
        hi, lo, cur = max(older), min(older), recent[-1]
        if max(recent) >= hi + c.sweep_min_pierce and cur < hi:
            self._last_sweep = (now, -1.0)   # buy-side liquidity swept above swing high, then rejected
        elif min(recent) <= lo - c.sweep_min_pierce and cur > lo:
            self._last_sweep = (now, 1.0)    # sell-side liquidity swept below swing low, then reclaimed

    def liquidity_sweep(self, now: datetime) -> tuple[float, float] | None:
        if not self._spot:
            return None
        if self._last_sweep is None:
            return 0.0, 0.0
        t, d = self._last_sweep
        age = (now - t).total_seconds()
        return (d, age) if 0 <= age <= self.cfg.sweep_lookback_seconds else (0.0, 0.0)

    def features(self, now: datetime) -> InstitutionalFeatures:
        now = _sanitize(now)
        v = dict(NEUTRAL)
        avail = dict.fromkeys(_AVAIL, 0.0)
        if (sw := self.liquidity_sweep(now)) is not None:
            v["spot_liquidity_sweep"], v["spot_sweep_age_seconds"] = sw
            avail["sweep"] = 1.0
        if self.available:
            if (bi := self.book_imbalance(now)) is not None:
                v["inst_book_imbalance"], avail["book"] = bi, 1.0
            if (ar := self.aggressive_buy_ratio(now)) is not None:
                v["inst_aggressive_buy_ratio"], avail["prints"] = ar, 1.0
            if (bz := self.basis(now)) is not None:
                (v["inst_basis"], v["inst_basis_z"]), avail["basis"] = bz, 1.0
            if (oi := self.oi_change(now)) is not None:
                (v["inst_oi_change"], v["inst_oi_change_pct"]), avail["oi"] = oi, 1.0
            if (cp := self.cot_percentile(now)) is not None:
                v["inst_cot_mm_net_pct"], avail["cot"] = cp, 1.0
        v.update({f"inst_{k}_available": a for k, a in avail.items()})
        return InstitutionalFeatures(self.available, v, self.configured_sources)
