"""Risk Management Agent — independent, deterministic veto over every trade proposal.

The decision agent cannot bypass this: every engine (backtest, walk-forward,
virtual, real) routes proposals through `RiskEngine.evaluate` before opening.
No martingale, grid or recovery sizing exists anywhere in the codebase: lot size
depends only on equity, stop distance and configured risk %, never on previous outcomes.
Rules are listed in docs/AGENTIC_REDESIGN.md §5 (R1-R23); every verdict reports all failing
rules and the rule-set version, so a blocked trade can always be explained.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..config import RiskConfig
from ..domain import Side, SymbolSpec, Tick, TradeProposal
from ..timeutil import in_local_window


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
    rule_version: str = ""


@dataclass
class RiskState:
    start_of_day_equity: float
    peak_equity: float
    day: date | None = None
    realized_today: float = 0.0
    emergency_stop: bool = False
    emergency_reason: str = ""
    connected: bool = True
    week: tuple[int, int] | None = None
    start_of_week_equity: float = 0.0
    consecutive_losses: int = 0
    last_loss_time: datetime | None = None
    cooldown_until: datetime | None = None
    cooldown_reason: str = ""
    trades_today: int = 0
    last_entry_time: datetime | None = None
    recent_keys: dict = field(default_factory=dict)       # proposal key -> time (duplicate prevention)
    overrides: list[dict] = field(default_factory=list)   # recorded manual overrides (never bypass limits)
    reconciled: bool = True                               # false after a disconnect/restart until reconciled


@dataclass
class RiskEngine:
    cfg: RiskConfig
    spec: SymbolSpec
    state: RiskState
    news: list[NewsEvent] = field(default_factory=list)
    mode: str = "virtual"                 # virtual | demo | real; the observation window gates demo/real only
    started_at: datetime | None = None    # set by start(); None = no observation window tracked

    @classmethod
    def create(cls, cfg: RiskConfig, spec: SymbolSpec, equity: float) -> "RiskEngine":
        return cls(cfg, spec, RiskState(start_of_day_equity=equity, peak_equity=equity))

    def rule_version(self) -> str:
        blob = json.dumps(self.cfg.model_dump(), sort_keys=True, default=str).encode()
        return "risk-" + hashlib.sha256(blob).hexdigest()[:10]

    def start(self, mode: str, now: datetime) -> None:
        """Begin a session: in demo/real mode no entry is approved during the observation window."""
        if mode not in ("virtual", "demo", "real"):
            raise ValueError(f"unknown mode {mode!r}")
        self.mode, self.started_at = mode, now

    # -- state updates -------------------------------------------------------
    def on_equity(self, equity: float, now: datetime) -> None:
        if self.state.day != now.date():
            self.state.day = now.date()
            self.state.start_of_day_equity = equity
            self.state.realized_today = 0.0
            self.state.trades_today = 0
        wk = tuple(now.isocalendar())[:2]
        if self.state.week != wk:
            self.state.week = wk
            self.state.start_of_week_equity = equity
        self.state.peak_equity = max(self.state.peak_equity, equity)

    @staticmethod
    def _key(p: TradeProposal) -> tuple:
        return (p.side.value, round(p.entry, 6), p.valid_until.isoformat(), p.strategy_version)

    def on_trade_opened(self, now: datetime, proposal: TradeProposal | None = None) -> None:
        s = self.state
        s.trades_today += 1
        s.last_entry_time = now
        if proposal is not None:
            s.recent_keys = {k: t for k, t in s.recent_keys.items()
                             if (now - t).total_seconds() <= self.cfg.duplicate_window_seconds}
            s.recent_keys[self._key(proposal)] = now

    def on_trade_closed(self, net_pnl: float, now: datetime | None = None) -> None:
        s = self.state
        s.realized_today += net_pnl
        if net_pnl < 0:
            s.consecutive_losses += 1
            s.last_loss_time = now
            if now is not None and s.consecutive_losses >= self.cfg.max_consecutive_losses:
                s.cooldown_until = now + timedelta(minutes=self.cfg.loss_cooldown_minutes)
                s.cooldown_reason = f"{s.consecutive_losses} consecutive losses"
                s.consecutive_losses = 0
        else:
            s.consecutive_losses = 0

    def on_disconnect(self) -> None:
        self.state.connected = False
        self.state.reconciled = False

    def on_reconnected(self, reconciled: bool) -> None:
        """Reconnection alone is not enough: entries stay blocked until positions were reconciled."""
        self.state.connected = True
        self.state.reconciled = reconciled

    def record_override(self, actor: str, rule: str, reason: str, now: datetime) -> dict:
        """Record a manual override request. It is logged for behaviour review and never relaxes a limit."""
        o = {"time": now.isoformat(), "actor": actor, "rule": rule, "reason": reason, "applied": False}
        self.state.overrides.append(o)
        return o

    def overrides_recent(self, now: datetime, hours: float = 24) -> int:
        cut = now - timedelta(hours=hours)
        return sum(1 for o in self.state.overrides if datetime.fromisoformat(o["time"]) >= cut)

    def validate_stop_change(self, side: Side, current_sl: float, new_sl: float) -> RiskVerdict:
        """A stop may only move in the direction that reduces risk. Never widen a stop to avoid a loss."""
        widen = new_sl < current_sl if side == Side.BUY else new_sl > current_sl
        if widen:
            return RiskVerdict(False, [f"stop change {current_sl} -> {new_sl} widens risk"],
                               rule_version=self.rule_version())
        return RiskVerdict(True, [], rule_version=self.rule_version())

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
                 now: datetime | None = None, *, market: dict | None = None, latency_ms: float | None = None,
                 free_margin: float | None = None) -> RiskVerdict:
        """`market` may carry measured inputs (vol_ratio, spread_z) from the market agent; checks that need
        a measurement only apply when it is supplied."""
        now = now or tick.time
        cfg = self.cfg
        r: list[str] = []
        s = self.state
        rv = self.rule_version()
        if p.side == Side.WAIT:
            return RiskVerdict(False, ["WAIT decision"], rule_version=rv)
        exploring = "[EXPLORATION]" in p.explanation
        if s.emergency_stop:
            r.append(f"emergency stop active: {s.emergency_reason}")
        if not s.connected:
            r.append("broker connectivity requirement not met")
        elif not s.reconciled:
            r.append("account not reconciled after reconnect/restart")
        if self.mode in ("demo", "real") and self.started_at is not None:
            until = self.started_at + timedelta(minutes=cfg.observation_minutes)
            if now < until:
                r.append(f"observation window: virtual only until {until.strftime('%H:%M:%S')} UTC")
        if open_positions >= cfg.max_open_positions:
            r.append(f"position limit reached ({open_positions}/{cfg.max_open_positions})")
        if (now - tick.time).total_seconds() > cfg.max_tick_age_seconds:
            r.append("market data stale")
        spread_pts = tick.spread / self.spec.point
        if spread_pts > cfg.max_spread_points:
            r.append(f"spread {spread_pts:.0f} pts > {cfg.max_spread_points}")
        m = market or {}
        if m.get("spread_z") is not None and m["spread_z"] > cfg.max_spread_z:
            r.append(f"abnormal spread widening (z {m['spread_z']:.1f} > {cfg.max_spread_z})")
        if m.get("vol_ratio") is not None and m["vol_ratio"] > cfg.max_vol_ratio:
            r.append(f"abnormal volatility (ratio {m['vol_ratio']:.1f} > {cfg.max_vol_ratio})")
        if latency_ms is not None and latency_ms > cfg.max_latency_ms:
            r.append(f"execution latency {latency_ms:.0f} ms > {cfg.max_latency_ms:.0f} ms")
        dd_pct = (s.peak_equity - equity) / s.peak_equity * 100 if s.peak_equity > 0 else 0
        if dd_pct >= cfg.max_drawdown_pct:
            r.append(f"max drawdown {dd_pct:.2f}% reached")
        day_loss_pct = (s.start_of_day_equity - equity) / s.start_of_day_equity * 100 if s.start_of_day_equity else 0
        if day_loss_pct >= cfg.max_daily_loss_pct:
            r.append(f"daily loss {day_loss_pct:.2f}% reached")
        wk_eq = s.start_of_week_equity or s.start_of_day_equity
        week_loss_pct = (wk_eq - equity) / wk_eq * 100 if wk_eq else 0
        if week_loss_pct >= cfg.max_weekly_loss_pct:
            r.append(f"weekly loss {week_loss_pct:.2f}% reached")
        if s.cooldown_until is not None and now < s.cooldown_until:
            r.append(f"cooldown after {s.cooldown_reason} until {s.cooldown_until.strftime('%H:%M')} UTC")
        if (s.last_loss_time is not None and
                now < s.last_loss_time + timedelta(minutes=cfg.reentry_after_loss_minutes)):
            r.append(f"re-entry blocked for {cfg.reentry_after_loss_minutes:g} min after a loss")
        if s.trades_today >= cfg.max_trades_per_day:
            r.append(f"overtrading: {s.trades_today} trades today (max {cfg.max_trades_per_day})")
        if (s.last_entry_time is not None and
                now < s.last_entry_time + timedelta(minutes=cfg.min_minutes_between_entries)):
            r.append(f"entries less than {cfg.min_minutes_between_entries:g} min apart")
        seen = s.recent_keys.get(self._key(p))
        if seen is not None and (now - seen).total_seconds() <= cfg.duplicate_window_seconds:
            r.append("duplicate proposal")
        if (ev := self.blocked_by_news(now)) is not None:
            r.append(f"news blackout: {ev.title}")
        if not self.in_session(now):
            r.append("outside allowed trading session")
        if cfg.allowed_sessions_local and not in_local_window(now, cfg.allowed_sessions_local, cfg.local_timezone):
            r.append(f"outside owner's {cfg.local_timezone} sessions")
        if p.risk_reward < cfg.min_risk_reward:
            r.append(f"risk/reward {p.risk_reward:.2f} < {cfg.min_risk_reward}")
        if p.confidence < cfg.min_confidence and not exploring:
            r.append(f"confidence {p.confidence:.2f} < {cfg.min_confidence}")
        if p.ev_after_cost_r is not None and not exploring and p.ev_after_cost_r < cfg.min_ev_after_cost_r:
            r.append(f"expected value after costs {p.ev_after_cost_r:.2f}R < {cfg.min_ev_after_cost_r}R")
        min_d = self.spec.min_stop_distance
        if abs(p.entry - p.stop_loss) < min_d or abs(p.take_profit - p.entry) < min_d:
            r.append("SL/TP inside broker stop level")
        if (p.side == Side.BUY and p.stop_loss >= p.entry) or (p.side == Side.SELL and p.stop_loss <= p.entry):
            r.append("stop loss missing or on the wrong side of entry")
        if self.spec.trade_mode in ("disabled", "closeonly"):
            r.append(f"symbol trade mode {self.spec.trade_mode}")
        lots = min(p.lots, cfg.max_lots_per_trade, self.position_size(equity, p.entry, p.stop_loss))
        lots = self.spec.round_volume(lots)
        if lots <= 0:
            r.append("lot size below broker minimum at configured risk")
        if free_margin is not None and self.spec.margin_initial > 0 and lots > 0:
            need = self.spec.margin_initial * lots
            if free_margin <= 0 or need / free_margin * 100 > cfg.max_margin_use_pct:
                r.append(f"margin {need:.2f} > {cfg.max_margin_use_pct:g}% of free margin")
        return RiskVerdict(not r, r, lots if not r else 0.0, rv)
