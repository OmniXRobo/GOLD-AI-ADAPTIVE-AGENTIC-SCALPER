"""Trade Context Agent: a snapshot of technical, news, intermarket and regime data stored with every virtual trade.

The decision model learns only from its fixed feature set (market/features.py). This agent records a wider picture
at the moment each trade is opened, in `trade.context["context"]`, so the Trade-History Learner
(agents/trade_learner.py) can measure later, on closed trades, which of these data actually relate to outcomes,
before any of them is allowed into a decision. Nothing here changes a decision.

Recorded (each field is left out when its data is not available):
- technical: the research feature set (research/features.py), e.g. spread/ATR, Bollinger band-width percentile,
  ADX, MACD, VWAP and volume-profile distances, prefixed `tech_`;
- news: minutes to the next and since the last high-impact event in the instrument's currencies, and the
  surprise of the last released one, (actual - forecast) / |forecast|, when the calendar has both values;
- intermarket: US-dollar strength over the last 60 minutes from the forex majors the service watches (basis
  points, positive = USD stronger), and the instrument's own 60-minute return;
- regime: the HMM regime agent's label, confidence, change-point probability and `uncertain` flag.
"""
from __future__ import annotations

import math
import threading
from collections import deque
from datetime import datetime, timedelta

from ..agents.regime import RegimeAgent
from ..domain import Tick
from ..instruments import canonical
from ..research.features import feature_vector

# Forex majors and the sign that turns their return into US-dollar strength.
USD_PAIRS = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1, "USDJPY": 1, "USDCHF": 1, "USDCAD": 1}


def currencies_of(symbol: str) -> set[str]:
    c = canonical(symbol) or symbol
    if c in ("XAUUSD", "BTCUSD"):
        return {"USD"}
    return {c[:3], c[3:6]} if len(c) >= 6 else {"USD"}


class IntermarketMonitor:
    """Mid prices per canonical instrument, sampled about once a minute, kept for a few hours."""

    def __init__(self, keep: timedelta = timedelta(hours=3)):
        self.keep = keep
        self._px: dict[str, deque] = {}
        self._lock = threading.Lock()

    def observe(self, symbol: str, tick: Tick | None) -> None:
        if tick is None or tick.bid <= 0 or tick.ask <= 0:
            return
        name = canonical(symbol) or symbol
        with self._lock:
            q = self._px.setdefault(name, deque())
            if q and tick.time <= q[-1][0]:
                return
            q.append((tick.time, (tick.bid + tick.ask) / 2))
            while q and q[0][0] < tick.time - self.keep:
                q.popleft()

    def return_bp(self, name: str, now: datetime, minutes: int = 60) -> float | None:
        with self._lock:
            q = list(self._px.get(name, ()))
        if len(q) < 2 or now - q[-1][0] > timedelta(minutes=5):
            return None
        past = [p for t, p in q if t <= now - timedelta(minutes=minutes)]
        if not past or past[-1] <= 0:
            return None
        return math.log(q[-1][1] / past[-1]) * 1e4

    def usd_strength_bp(self, now: datetime, minutes: int = 60) -> tuple[float | None, int]:
        rs = [sign * r for pair, sign in USD_PAIRS.items() if (r := self.return_bp(pair, now, minutes)) is not None]
        return (sum(rs) / len(rs) if rs else None), len(rs)


class TradeContextAgent:
    def __init__(self, news=None, intermarket: IntermarketMonitor | None = None, regime_bars: int = 300):
        self.news = news
        self.intermarket = intermarket
        self.regime_bars = regime_bars

    def snapshot(self, symbol: str, tick: Tick, state) -> dict:
        out: dict = {}
        for part in (self._technical, self._news, self._intermarket, self._regime):
            try:
                out.update(part(symbol, tick, state))
            except Exception as e:                 # a missing data source never blocks a trade
                out.setdefault("errors", []).append(f"{part.__name__}: {type(e).__name__}")
        return out

    @staticmethod
    def _technical(symbol, tick, state) -> dict:
        bars = state.bars or {}
        m1, m5, m15 = bars.get("M1", []), bars.get("M5", []), bars.get("M15", [])
        f = feature_vector(m1, m5, m15) if m1 and m5 and m15 else None
        return {f"tech_{k}": round(v, 5) for k, v in (f or {}).items()}

    def _news(self, symbol, tick, state) -> dict:
        if self.news is None:
            return {}
        cur = currencies_of(symbol)
        evs = [e for e in self.news.events() if e.impact == "high" and (e.currency or "").upper() in cur | {"ALL"}]
        now = tick.time
        nxt = min((e.time for e in evs if e.time > now), default=None)
        past = [e for e in evs if e.time <= now]
        out: dict = {}
        if nxt is not None:
            out["news_minutes_to_next_high"] = round((nxt - now).total_seconds() / 60, 1)
        if past:
            last = max(past, key=lambda e: e.time)
            out["news_minutes_since_last_high"] = round((now - last.time).total_seconds() / 60, 1)
            if last.actual is not None and last.forecast not in (None, 0):
                out["news_last_high_surprise"] = round((last.actual - last.forecast) / abs(last.forecast), 4)
                out["news_last_high_currency"] = last.currency
        return out

    def _intermarket(self, symbol, tick, state) -> dict:
        if self.intermarket is None:
            return {}
        out: dict = {}
        usd, n = self.intermarket.usd_strength_bp(tick.time)
        if usd is not None:
            out["usd_strength_60m_bp"], out["usd_strength_pairs"] = round(usd, 2), n
        own = self.intermarket.return_bp(canonical(symbol) or symbol, tick.time)
        if own is not None:
            out["own_return_60m_bp"] = round(own, 2)
        return out

    def _regime(self, symbol, tick, state) -> dict:
        bars = (state.bars or {}).get("M5", [])[-self.regime_bars:]
        if len(bars) < 150:                          # 100 bars to fit, 50 to filter forward
            return {}
        agent = RegimeAgent().fit(bars[:-50])        # fitted on older bars, then filtered forward: causal
        r = None
        for b in bars[-50:]:
            r = agent.update(b)
        if r is None:
            return {}
        return {"regime_hmm": r.state_label, "regime_hmm_confidence": r.confidence,
                "regime_hmm_change_point": r.change_point_prob, "regime_hmm_uncertain": r.uncertain}
