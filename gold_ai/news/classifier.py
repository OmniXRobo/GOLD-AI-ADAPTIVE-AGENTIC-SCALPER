"""Rule-based event classifier: title -> category, impact and uncertainty.

Deterministic keyword rules, evaluated in order (first match wins), so it is
cheap enough to run on every calendar refresh. Owners can prepend overrides
(regex -> category/impact/uncertainty) for their provider's naming quirks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .events import IMPACT_RANK, EconomicEvent, EventCategory


@dataclass(frozen=True)
class Rule:
    pattern: str                 # case-insensitive regex searched in the title
    category: EventCategory
    impact: str
    uncertainty: float

    def matches(self, title: str) -> bool:
        return re.search(self.pattern, title, re.IGNORECASE) is not None


# Order matters: speeches before FOMC (an "FOMC Member X Speaks" is a speech),
# claims before unemployment rate.
DEFAULT_RULES: tuple[Rule, ...] = (
    Rule(r"\b(fed|fomc|federal reserve|powell)\b.*\b(speaks|speech|testif\w*|testimony|remarks)\b|"
         r"\bfed chair\b|\bpowell\b", EventCategory.FED_SPEECH, "medium", 0.6),
    Rule(r"\bfomc\b|federal funds rate|fed (interest )?rate decision|interest rate decision.*\bfed\b|"
         r"\bfed\b.*interest rate decision", EventCategory.FOMC, "high", 0.9),
    Rule(r"non[- ]?farm|\bnfp\b|payrolls", EventCategory.NFP, "high", 0.85),
    Rule(r"jobless claims|unemployment claims|initial claims|continuing claims", EventCategory.JOBLESS_CLAIMS,
         "medium", 0.4),
    Rule(r"unemployment rate", EventCategory.UNEMPLOYMENT, "high", 0.7),
    Rule(r"\bcpi\b|consumer price", EventCategory.CPI, "high", 0.8),
    Rule(r"\bppi\b|producer price", EventCategory.PPI, "medium", 0.55),
    Rule(r"\bpce\b|personal consumption expenditure", EventCategory.PCE, "high", 0.65),
    Rule(r"\bgdp\b|gross domestic product", EventCategory.GDP, "medium", 0.55),
    Rule(r"(bond|note|bill|treasury|t-bond|t-note)s? auction|\d+-?(y|yr|year) .*auction", EventCategory.TREASURY_AUCTION,
         "low", 0.3),
    Rule(r"\b(war|invasion|invade[sd]?|missile|airstrike|sanction[s]?|military|ceasefire|attack|conflict|"
         r"geopolitic\w*|nuclear|coup|terror\w*)\b", EventCategory.GEOPOLITICAL, "high", 0.95),
)


@dataclass(frozen=True)
class Classification:
    category: EventCategory
    impact: str
    uncertainty: float


@dataclass
class EventClassifier:
    overrides: list[Rule] = field(default_factory=list)   # checked before the defaults
    rules: tuple[Rule, ...] = DEFAULT_RULES
    relevant_currencies: tuple[str, ...] = ("USD",)       # gold is priced in USD
    missing_forecast_uncertainty: float = 0.1

    def add_override(self, pattern: str, category: str | EventCategory, impact: str,
                     uncertainty: float = 0.5) -> None:
        if impact not in IMPACT_RANK:
            raise ValueError(f"impact must be one of {list(IMPACT_RANK)}")
        self.overrides.append(Rule(pattern, EventCategory(category), impact, uncertainty))

    def classify_title(self, title: str) -> Classification | None:
        for rule in (*self.overrides, *self.rules):
            if rule.matches(title):
                return Classification(rule.category, rule.impact, rule.uncertainty)
        return None

    def classify(self, ev: EconomicEvent) -> EconomicEvent:
        c = self.classify_title(ev.title)
        if c is None:
            # Unknown title: trust the provider's impact rating, else assume low.
            impact = ev.impact or "low"
            return ev.with_classification(EventCategory.OTHER.value, impact,
                                          {"high": 0.6, "medium": 0.4, "low": 0.2}[impact])
        impact = c.impact
        if ev.impact and IMPACT_RANK[ev.impact] > IMPACT_RANK[impact]:
            impact = ev.impact   # never downgrade what the provider flags as more important
        if (ev.currency.upper() not in self.relevant_currencies and c.category != EventCategory.GEOPOLITICAL):
            impact = ["low", "low", "medium"][IMPACT_RANK[impact]]
        unc = c.uncertainty
        if ev.forecast is None and c.category not in (EventCategory.FED_SPEECH, EventCategory.GEOPOLITICAL):
            unc += self.missing_forecast_uncertainty
        return ev.with_classification(c.category.value, impact, round(min(1.0, unc), 4))
