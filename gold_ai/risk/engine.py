"""Risk Management Agent — independent veto over every trade proposal.

The decision agent cannot bypass this: every engine (backtest, walk-forward,
virtual, real) routes proposals through `RiskEngine.evaluate` before opening.
No martingale, grid or recovery sizing exists anywhere in the codebase: lot size
depends only on equity, stop distance and configured risk %.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..config import RiskConfig
from ..domain import Side, SymbolSpec, Tick, TradeProposal


@dataclass(frozen=True)
class NewsEvent:
    time: datetime
    title: str
    impact: str  # "high" | "medium" | "low"
    currency: str = "USD"


@dataclass
class RiskVerdict:
    approved: bool
    reasons: list[str]
    lots: float = 0.0


@dataclass
class RiskState:
    start_of_day_equity: float
    peak_equity: float
    day: date | None = None
    realized_today: float = 0.0
    emergency_stop: bool = False
    emergency_reason: str = ""
    connected: bool = True


@dataclass
class RiskEngine:
    cfg: RiskConfig
    spec: SymbolSpec
    state: RiskState
    news: list[NewsEvent] = field(default_factory=list)

    @classmethod
    def create(cls, cfg: RiskConfig, spec: SymbolSpec, equity: float) -> "RiskEngine":
        return cls(cfg, spec, RiskState(start_of_day_equity=equity, peak_equity=equity))

    # -- state updates -------------------------------------------------------
    def on_equity(self, equity: float, now: datetime) -> None:
        if self.state.day != now.date():
            self.state.day = now.date()
            self.state.start_of_day_equity = equity
            self.state.realized_today = 0.0
        self.state.peak_equity = max(self.state.peak_equity, equity)

    def on_trade_closed(self, net_pnl: float) -> None:
        self.state.realized_today += net_pnl

    def trigger_emergency_stop(self, reason: str) -> None:
        self.state.emergency_stop = True
        self.state.emergency_reason = reason

    def clear_emergency_stop(self) -> None:
        self.state.emergency_stop = False
        self.state.emergency_reason = ""

    # -- sizing ------------------------------------------------------------------
    def position_size(self, equity: float, entry: float, stop: float) -> float:
        dist = abs(entry - stop)
        if dist <= 0 or equity <= 0:
            return 0.0
        risk_money = equity * self.cfg.risk_per_trade_pct / 100.0
        per_lot = self.spec.money_per_price_unit(1.0) * dist
        lots = min(risk_money / per_lot, self.cfg.max_lots_per_trade)
        return self.spec.round_volume(lots)

    # -- veto ------------------------------------------------------------------
    def blocked_by_news(self, now: datetime) -> NewsEvent | None:
        before = timedelta(minutes=self.cfg.block_minutes_before_high_impact)
        after = timedelta(minutes=self.cfg.block_minutes_after_high_impact)
        only = {c.upper() for c in self.cfg.news_currencies}
        for ev in self.news:
            if only and ev.currency and ev.currency.upper() not in only and ev.currency.upper() != "ALL":
                continue
            if ev.impact == "high" and ev.time - before <= now <= ev.time + after:
                return ev
        return None

    def in_session(self, now: datetime) -> bool:
        h = now.hour + now.minute / 60
        return any(a <= h < b for a, b in self.cfg.allowed_sessions_utc)

    def evaluate(self, p: TradeProposal, tick: Tick, equity: float, open_positions: int,
                 now: datetime | None = None) -> RiskVerdict:
        now = now or tick.time
        r: list[str] = []
        s = self.state
        if p.side == Side.WAIT:
            return RiskVerdict(False, ["WAIT decision"])
        if s.emergency_stop:
            r.append(f"emergency stop active: {s.emergency_reason}")
        if not s.connected:
            r.append("broker connectivity requirement not met")
        if open_positions >= self.cfg.max_open_positions:
            r.append(f"position limit reached ({open_positions}/{self.cfg.max_open_positions})")
        if (now - tick.time).total_seconds() > self.cfg.max_tick_age_seconds:
            r.append("market data stale")
        spread_pts = tick.spread / self.spec.point
        if spread_pts > self.cfg.max_spread_points:
            r.append(f"spread {spread_pts:.0f} pts > {self.cfg.max_spread_points}")
        dd_pct = (s.peak_equity - equity) / s.peak_equity * 100 if s.peak_equity > 0 else 0
        if dd_pct >= self.cfg.max_drawdown_pct:
            r.append(f"max drawdown {dd_pct:.2f}% reached")
        day_loss_pct = (s.start_of_day_equity - equity) / s.start_of_day_equity * 100 if s.start_of_day_equity else 0
        if day_loss_pct >= self.cfg.max_daily_loss_pct:
            r.append(f"daily loss {day_loss_pct:.2f}% reached")
        if (ev := self.blocked_by_news(now)) is not None:
            r.append(f"news blackout: {ev.title}")
        if not self.in_session(now):
            r.append("outside allowed trading session")
        if p.risk_reward < self.cfg.min_risk_reward:
            r.append(f"risk/reward {p.risk_reward:.2f} < {self.cfg.min_risk_reward}")
        if p.confidence < self.cfg.min_confidence and "[EXPLORATION]" not in p.explanation:
            r.append(f"confidence {p.confidence:.2f} < {self.cfg.min_confidence}")
        min_d = self.spec.min_stop_distance
        if abs(p.entry - p.stop_loss) < min_d or abs(p.take_profit - p.entry) < min_d:
            r.append("SL/TP inside broker stop level")
        if self.spec.trade_mode in ("disabled", "closeonly"):
            r.append(f"symbol trade mode {self.spec.trade_mode}")
        lots = min(p.lots, self.cfg.max_lots_per_trade, self.position_size(equity, p.entry, p.stop_loss))
        lots = self.spec.round_volume(lots)
        if lots <= 0:
            r.append("lot size below broker minimum at configured risk")
        return RiskVerdict(not r, r, lots if not r else 0.0)
