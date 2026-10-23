"""Broker-specific transaction cost model: spread, commission, swap, slippage.

Fills are always Bid/Ask aware: BUY enters at Ask and exits at Bid; SELL enters at
Bid and exits at Ask. Slippage is applied adversely (conservative).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import CostConfig
from .domain import Side, SymbolSpec, Tick


@dataclass
class CostModel:
    spec: SymbolSpec
    cfg: CostConfig

    def entry_fill(self, side: Side, tick: Tick) -> float:
        slip = self.cfg.slippage_points_entry * self.spec.point
        return tick.ask + slip if side == Side.BUY else tick.bid - slip

    def exit_fill(self, side: Side, tick: Tick, is_stop: bool = False) -> float:
        pts = self.cfg.slippage_points_exit + (self.cfg.stop_slippage_extra_points if is_stop else 0)
        slip = pts * self.spec.point
        return tick.bid - slip if side == Side.BUY else tick.ask + slip

    def stop_fill(self, side: Side, trigger_price: float, tick: Tick) -> float:
        """Stop orders fill at the worse of the stop level and the current market, minus slippage."""
        market = self.exit_fill(side, tick, is_stop=True)
        if side == Side.BUY:
            return min(trigger_price - self.cfg.stop_slippage_extra_points * self.spec.point, market)
        return max(trigger_price + self.cfg.stop_slippage_extra_points * self.spec.point, market)

    def commission(self, lots: float) -> float:
        """Round-turn commission in account currency."""
        return 2.0 * self.spec.commission_per_lot_side * lots

    def swap(self, side: Side, lots: float, entry: datetime, exit: datetime) -> float:
        """Swap charged per rollover crossed (00:00 server time approximated as UTC).

        Rollovers on `triple_swap_weekday` (Wednesday, the MT5 default for metals and forex) are
        charged triple; crypto has no triple day and is charged every night. Returns
        signed account-currency amount (negative = cost).
        """
        nights = 0
        triple = 0
        d = entry.date()
        while d < exit.date():
            nights += 1
            if d.weekday() == self.cfg.triple_swap_weekday:
                triple += 1
            d = d.fromordinal(d.toordinal() + 1)
        charge_units = nights + 2 * triple
        rate = self.spec.swap_long if side == Side.BUY else self.spec.swap_short
        if self.spec.swap_mode == "points":
            per_night = rate * self.spec.point * self.spec.money_per_price_unit(lots)
        else:
            per_night = rate * lots
        return per_night * charge_units

    def spread_cost(self, lots: float, tick: Tick) -> float:
        return tick.spread * self.spec.money_per_price_unit(lots)

    def estimated_round_trip(self, lots: float, tick: Tick) -> float:
        """Expected cost of opening+closing immediately (spread + commission + slippage)."""
        slip_pts = self.cfg.slippage_points_entry + self.cfg.slippage_points_exit
        slip = slip_pts * self.spec.point * self.spec.money_per_price_unit(lots)
        return self.spread_cost(lots, tick) + self.commission(lots) + slip
