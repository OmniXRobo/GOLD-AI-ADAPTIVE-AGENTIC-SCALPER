"""Bid/Ask-aware position simulator shared by all three testing engines.

Rules (conservative by design):
- BUY opens at Ask (+slippage), is closed at Bid; SELL opens at Bid (-slippage), closed at Ask.
- BUY SL/TP trigger on Bid; SELL SL/TP trigger on Ask.
- If SL and TP are both crossed by the same tick, the stop is assumed to fill first.
- Stops fill at the worse of the stop level and the market, minus extra stop slippage.
- Take-profits fill exactly at the TP level (no positive slippage).
- Trailing stop only ever tightens.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from ..costs import CostModel
from ..domain import ExitReason, Side, SimTrade, Tick, TradeProposal


@dataclass
class OpenPosition:
    trade: SimTrade
    trailing_start: float | None
    trailing_distance: float | None
    valid_until: datetime | None
    trailing_active: bool = False
    current_sl: float = 0.0


@dataclass
class PositionSimulator:
    costs: CostModel
    broker: str
    account: str
    max_open: int = 1
    max_hold_seconds: float | None = None
    positions: list[OpenPosition] = field(default_factory=list)
    closed: list[SimTrade] = field(default_factory=list)

    def can_open(self) -> bool:
        return len(self.positions) < self.max_open

    def open(self, p: TradeProposal, tick: Tick, context: dict | None = None) -> SimTrade | None:
        if p.side == Side.WAIT or not self.can_open():
            return None
        spec = self.costs.spec
        lots = spec.round_volume(p.lots)
        if lots <= 0:
            return None
        fill = self.costs.entry_fill(p.side, tick)
        # Validate stops against fill and broker stop level; reject rather than silently move.
        min_d = spec.min_stop_distance
        if p.side == Side.BUY and not (p.stop_loss < fill - min_d and p.take_profit > fill + min_d):
            return None
        if p.side == Side.SELL and not (p.stop_loss > fill + min_d and p.take_profit < fill - min_d):
            return None
        mpu = spec.money_per_price_unit(lots)
        quoted = tick.ask if p.side == Side.BUY else tick.bid
        t = SimTrade(
            trade_id=uuid.uuid4().hex, broker=self.broker, account=self.account, symbol=spec.symbol,
            side=p.side, lots=lots, entry_time=tick.time, entry_price=fill,
            stop_loss=p.stop_loss, take_profit=p.take_profit,
            strategy_version=p.strategy_version, model_version=p.model_version,
            spread_cost=self.costs.spread_cost(lots, tick),
            slippage_cost=abs(fill - quoted) * mpu,
            initial_risk_money=abs(fill - p.stop_loss) * mpu,
            context=dict(context or {}), explanation=p.explanation,
        )
        self.positions.append(OpenPosition(t, p.trailing_start, p.trailing_distance, p.valid_until,
                                           current_sl=p.stop_loss))
        return t

    def on_tick(self, tick: Tick) -> list[SimTrade]:
        done = []
        for pos in list(self.positions):
            reason, price = self._check(pos, tick)
            if reason is not None:
                done.append(self._close(pos, tick, price, reason))
        return done

    def close_all(self, tick: Tick, reason: ExitReason) -> list[SimTrade]:
        out = []
        for pos in list(self.positions):
            out.append(self._close(pos, tick, self.costs.exit_fill(pos.trade.side, tick), reason))
        return out

    # -- internals -------------------------------------------------------
    def _check(self, pos: OpenPosition, tick: Tick) -> tuple[ExitReason | None, float]:
        t = pos.trade
        buy = t.side == Side.BUY
        px = tick.bid if buy else tick.ask
        fav = (px - t.entry_price) if buy else (t.entry_price - px)
        t.max_favorable = max(t.max_favorable, fav)
        t.max_adverse = min(t.max_adverse, fav)

        sl_hit = px <= pos.current_sl if buy else px >= pos.current_sl
        tp_hit = px >= t.take_profit if buy else px <= t.take_profit
        if sl_hit:
            reason = ExitReason.TRAILING_STOP if pos.trailing_active else ExitReason.STOP_LOSS
            return reason, self.costs.stop_fill(t.side, pos.current_sl, tick)
        if tp_hit:
            return ExitReason.TAKE_PROFIT, t.take_profit

        if pos.trailing_distance and pos.trailing_start is not None and fav >= pos.trailing_start:
            new_sl = px - pos.trailing_distance if buy else px + pos.trailing_distance
            if (buy and new_sl > pos.current_sl) or (not buy and new_sl < pos.current_sl):
                pos.current_sl = new_sl
                pos.trailing_active = True

        if self.max_hold_seconds and (tick.time - t.entry_time).total_seconds() >= self.max_hold_seconds:
            return ExitReason.EXPIRY, self.costs.exit_fill(t.side, tick)
        return None, 0.0

    def _close(self, pos: OpenPosition, tick: Tick, price: float, reason: ExitReason) -> SimTrade:
        t = pos.trade
        spec = self.costs.spec
        mpu = spec.money_per_price_unit(t.lots)
        direction = 1.0 if t.side == Side.BUY else -1.0
        t.exit_time = tick.time
        t.exit_price = price
        t.exit_reason = reason
        t.stop_loss = pos.current_sl
        t.gross_pnl = (price - t.entry_price) * direction * mpu
        t.commission = self.costs.commission(t.lots)
        t.swap = self.costs.swap(t.side, t.lots, t.entry_time, tick.time)
        if reason in (ExitReason.STOP_LOSS, ExitReason.TRAILING_STOP, ExitReason.EXPIRY,
                      ExitReason.EMERGENCY, ExitReason.END_OF_DATA, ExitReason.MANUAL):
            quoted = tick.bid if t.side == Side.BUY else tick.ask
            if reason in (ExitReason.STOP_LOSS, ExitReason.TRAILING_STOP):
                quoted = pos.current_sl
            t.slippage_cost += abs(quoted - price) * mpu
        t.net_pnl = t.gross_pnl - t.commission + t.swap
        self.positions.remove(pos)
        self.closed.append(t)
        return t
