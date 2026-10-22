"""Global News & Fundamental Agent.

Keeps a classified economic calendar, feeds high-impact events to the risk
engine's news blackout, and exposes event-window regime flags as features.

The optional LLM headline interpreter is asynchronous, rate-limited and never
required: it is meant to be called from a slow background job (minutes), never
from the per-tick decision path. The default interpreter does nothing.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from ..risk.engine import NewsEvent
from .classifier import EventClassifier
from .events import IMPACT_RANK, EconomicEvent
from .sources import NewsSource

log = logging.getLogger(__name__)

NO_EVENT_MINUTES = 1440.0   # neutral value for "minutes to/since" when there is no event


@dataclass(frozen=True)
class HeadlineInterpretation:
    headline: str
    gold_bias: float = 0.0      # -1 bearish .. +1 bullish for gold
    confidence: float = 0.0
    summary: str = ""


class HeadlineInterpreter(Protocol):
    async def interpret(self, headlines: list[str]) -> list[HeadlineInterpretation]: ...


class NoOpInterpreter:
    async def interpret(self, headlines: list[str]) -> list[HeadlineInterpretation]:
        return []


@dataclass
class NewsAgent:
    sources: list[NewsSource] = field(default_factory=list)
    classifier: EventClassifier = field(default_factory=EventClassifier)
    pre_event_minutes: int = 30
    post_event_minutes: int = 30
    interpreter: HeadlineInterpreter = field(default_factory=NoOpInterpreter)
    interpret_min_interval_seconds: float = 300.0
    _events: dict[tuple, EconomicEvent] = field(default_factory=dict, repr=False)
    source_errors: dict[str, str] = field(default_factory=dict)
    interpretations: list[HeadlineInterpretation] = field(default_factory=list)
    _last_interpret: float = field(default=float("-inf"), repr=False)

    # -- calendar -------------------------------------------------------------
    def refresh(self, start: datetime, end: datetime) -> int:
        """Pull from every source; a failing source is recorded and skipped. Returns events added/updated."""
        n = 0
        for src in self.sources:
            name = getattr(src, "name", type(src).__name__)
            try:
                n += self.add_events(src.fetch(start, end))
                self.source_errors.pop(name, None)
            except Exception as e:  # provider outages must not stop the agent
                self.source_errors[name] = type(e).__name__
                log.warning("news source %s failed: %s", name, type(e).__name__)
        return n

    def add_events(self, events: list[EconomicEvent]) -> int:
        for ev in events:
            self._events[ev.key] = self.classifier.classify(ev)
        return len(events)

    @property
    def events(self) -> list[EconomicEvent]:
        return sorted(self._events.values(), key=lambda e: e.time)

    def prune(self, before: datetime) -> None:
        self._events = {k: e for k, e in self._events.items() if e.time >= before}

    def upcoming(self, now: datetime, horizon: timedelta = timedelta(hours=24),
                 min_impact: str = "low") -> list[EconomicEvent]:
        lvl = IMPACT_RANK[min_impact]
        return [e for e in self.events if now <= e.time <= now + horizon and IMPACT_RANK[e.impact] >= lvl]

    # -- risk engine integration ---------------------------------------------
    def risk_events(self, min_impact: str = "low") -> list[NewsEvent]:
        lvl = IMPACT_RANK[min_impact]
        return [NewsEvent(time=e.time, title=e.title, impact=e.impact, currency=e.currency)
                for e in self.events if IMPACT_RANK[e.impact] >= lvl]

    def sync_risk_engine(self, engine) -> int:
        """Replace RiskEngine.news with the current calendar (the engine blacks out high-impact ones)."""
        engine.news = self.risk_events()
        return len(engine.news)

    # -- features ----------------------------------------------------------------
    def regime_flags(self, now: datetime) -> dict[str, float]:
        pre, post = timedelta(minutes=self.pre_event_minutes), timedelta(minutes=self.post_event_minutes)
        f = {"news_pre_event_high": 0.0, "news_post_event_high": 0.0, "news_pre_event_medium": 0.0,
             "news_post_event_medium": 0.0, "news_minutes_to_next_high": NO_EVENT_MINUTES,
             "news_minutes_since_last_high": NO_EVENT_MINUTES, "news_window_uncertainty": 0.0}
        for e in self.events:
            if e.impact not in ("high", "medium"):
                continue
            mins = (e.time - now).total_seconds() / 60.0
            in_pre = now < e.time and e.time - now <= pre
            in_post = e.time <= now <= e.time + post
            if in_pre:
                f[f"news_pre_event_{e.impact}"] = 1.0
            if in_post:
                f[f"news_post_event_{e.impact}"] = 1.0
            if in_pre or in_post:
                f["news_window_uncertainty"] = max(f["news_window_uncertainty"], e.uncertainty)
            if e.impact == "high":
                if mins >= 0:
                    f["news_minutes_to_next_high"] = min(f["news_minutes_to_next_high"], mins)
                else:
                    f["news_minutes_since_last_high"] = min(f["news_minutes_since_last_high"], -mins)
        return f

    # -- optional LLM interpretation (background only) -----------------------------
    async def interpret_headlines(self, headlines: list[str]) -> list[HeadlineInterpretation]:
        """Rate-limited; returns the cached result when called again within the minimum interval."""
        now = time.monotonic()
        if not headlines or now - self._last_interpret < self.interpret_min_interval_seconds:
            return self.interpretations
        self._last_interpret = now
        try:
            self.interpretations = list(await self.interpreter.interpret(headlines))
        except Exception as e:  # interpretation is advisory only
            log.warning("headline interpreter failed: %s", type(e).__name__)
        return self.interpretations
