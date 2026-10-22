"""Trade signal record for signal-only mode. A signal is advice; it never places an order."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum

from ..domain import Tick, TradeProposal, utcnow


class SignalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"      # owner approved; execution (if any) is a separate gated path
    REJECTED = "rejected"
    IGNORED = "ignored"
    MANUAL = "manual"          # owner says they handled it manually at their broker
    EXPIRED = "expired"


@dataclass
class Signal:
    id: str
    broker: str
    symbol: str
    side: str
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    suggested_lots: float
    spread: float
    estimated_costs: float
    confidence: float
    reason: str
    timestamp: datetime
    expiry: datetime
    status: SignalStatus = SignalStatus.PENDING
    deliveries: list[dict] = field(default_factory=list)
    acted_by: str | None = None
    acted_at: datetime | None = None

    @classmethod
    def from_proposal(cls, p: TradeProposal, tick: Tick, broker: str, symbol: str = "XAUUSD",
                      now: datetime | None = None) -> "Signal":
        return cls(
            id=uuid.uuid4().hex[:12], broker=broker, symbol=symbol, side=p.side.value, entry=p.entry,
            stop_loss=p.stop_loss, take_profit=p.take_profit, risk_reward=round(p.risk_reward, 4),
            suggested_lots=p.lots, spread=round(tick.spread, 6), estimated_costs=p.expected_cost,
            confidence=p.confidence, reason=p.explanation, timestamp=now or utcnow(), expiry=p.valid_until,
        )

    def is_expired(self, now: datetime) -> bool:
        return now > self.expiry

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        for k in ("timestamp", "expiry", "acted_at"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Signal":
        d = dict(d)
        d["status"] = SignalStatus(d["status"])
        for k in ("timestamp", "expiry", "acted_at"):
            d[k] = datetime.fromisoformat(d[k]) if d.get(k) else None
        return cls(**d)


def format_signal(s: Signal) -> str:
    """Plain-text message used by every channel. Always labeled signal-only."""
    exp = s.expiry.strftime("%H:%M:%S UTC")
    return (
        "SIGNAL ONLY — no order placed\n"
        f"{s.side} {s.symbol} @ {s.entry:.2f} ({s.broker})\n"
        f"SL {s.stop_loss:.2f} | TP {s.take_profit:.2f} | R:R {s.risk_reward:.2f}\n"
        f"Suggested lots {s.suggested_lots:.2f} | spread {s.spread:.2f} | est. costs {s.estimated_costs:.2f}\n"
        f"Confidence {s.confidence:.0%} (calibrated)\n"
        f"Reason: {s.reason}\n"
        f"Valid until {exp} | id {s.id}\n"
        "Approving records your decision only; it does not execute a trade."
    )
