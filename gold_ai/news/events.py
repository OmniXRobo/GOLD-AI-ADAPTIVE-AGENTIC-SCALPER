"""Economic calendar event types used by the news agent."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

IMPACT_RANK = {"low": 0, "medium": 1, "high": 2}


class EventCategory(str, Enum):
    FOMC = "fomc"                    # Fed rate decision / statement / minutes / press conference
    CPI = "cpi"
    PPI = "ppi"
    NFP = "nfp"
    UNEMPLOYMENT = "unemployment"    # unemployment rate
    JOBLESS_CLAIMS = "jobless_claims"
    PCE = "pce"
    GDP = "gdp"
    FED_SPEECH = "fed_speech"
    TREASURY_AUCTION = "treasury_auction"
    GEOPOLITICAL = "geopolitical"
    OTHER = "other"


@dataclass(frozen=True)
class EconomicEvent:
    time: datetime                   # scheduled release time, UTC
    title: str
    currency: str = "USD"
    impact: str = ""                 # provider impact if supplied ("high" | "medium" | "low" | "")
    category: str = ""               # filled by EventClassifier
    uncertainty: float = 0.0         # 0..1, filled by EventClassifier
    forecast: float | None = None
    previous: float | None = None
    actual: float | None = None
    source: str = ""

    def with_classification(self, category: str, impact: str, uncertainty: float) -> "EconomicEvent":
        return replace(self, category=category, impact=impact, uncertainty=uncertainty)

    @property
    def key(self) -> tuple:
        return (self.time, self.title.strip().lower(), self.currency.upper())


def normalize_impact(value) -> str:
    """Map common provider impact encodings to high/medium/low ('' if unknown)."""
    if value is None:
        return ""
    s = str(value).strip().lower()
    if s in ("high", "h", "3", "red", "holiday-high"):
        return "high"
    if s in ("medium", "med", "m", "moderate", "2", "orange"):
        return "medium"
    if s in ("low", "l", "1", "yellow", "none", "0"):
        return "low"
    return ""


def parse_time(value) -> datetime:
    """ISO-8601 string (naive = UTC) or unix epoch seconds/milliseconds."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        v = float(value)
        dt = datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
    else:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def parse_number(value) -> float | None:
    """Parse '0.3%', '250K', '-1.2M', '' -> float or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("%", "")
    if not s:
        return None
    mult = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}.get(s[-1].lower())
    if mult:
        s = s[:-1]
    try:
        return float(s) * (mult or 1.0)
    except ValueError:
        return None
