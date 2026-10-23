"""Trade signal record for signal-only mode. A signal is advice; it never places an order."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum

from ..domain import Tick, TradeProposal, utcnow
from ..instruments import instrument_for


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

    @property
    def digits(self) -> int:
        inst = instrument_for(self.symbol)
        return inst.display_digits if inst else 2

    def pips(self, distance: float) -> float | None:
        inst = instrument_for(self.symbol)
        return abs(distance) / inst.pip_size if inst else None

    def to_dict(self) -> dict:
        d = asdict(self)
        inst = instrument_for(self.symbol)
        d.update(instrument=inst.name if inst else self.symbol, asset_class=inst.asset_class if inst else None,
                 pip_size=inst.pip_size if inst else None, digits=self.digits,
                 sl_pips=self.pips(self.entry - self.stop_loss), tp_pips=self.pips(self.take_profit - self.entry))
        d["status"] = self.status.value
        for k in ("timestamp", "expiry", "acted_at"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Signal":
        d = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        d["status"] = SignalStatus(d["status"])
        for k in ("timestamp", "expiry", "acted_at"):
            d[k] = datetime.fromisoformat(d[k]) if d.get(k) else None
        return cls(**d)


def format_signal(s: Signal) -> str:
    """Plain-text message used by every channel. Always labeled signal-only."""
    exp = s.expiry.strftime("%H:%M:%S UTC")
    n = s.digits
    sl_p, tp_p = s.pips(s.entry - s.stop_loss), s.pips(s.take_profit - s.entry)
    sl_txt = f" ({sl_p:.1f} pips)" if sl_p is not None else ""
    tp_txt = f" ({tp_p:.1f} pips)" if tp_p is not None else ""
    return (
        "SIGNAL ONLY — no order placed\n"
        f"{s.side} {s.symbol} @ {s.entry:.{n}f} ({s.broker})\n"
        f"SL {s.stop_loss:.{n}f}{sl_txt} | TP {s.take_profit:.{n}f}{tp_txt} | R:R {s.risk_reward:.2f}\n"
        f"Suggested lots {s.suggested_lots:.2f} | spread {s.spread:.{n}f} | est. costs {s.estimated_costs:.2f}\n"
        f"Confidence {s.confidence:.0%} (calibrated)\n"
        f"Reason: {s.reason}\n"
        f"Valid until {exp} | id {s.id}\n"
        "Approving records your decision only; it does not execute a trade."
    )
