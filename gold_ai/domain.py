"""Core domain types shared by every module.

All prices are floats in quote currency; all timestamps are timezone-aware UTC
datetimes. Nothing here talks to a broker or a database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"


class MemoryDomain(str, Enum):
    """The four independent persistent memory histories (spec section 5)."""

    HISTORICAL = "historical"        # Memory A — backtests
    FORWARD = "forward"              # Memory B — walk-forward / out-of-sample
    VIRTUAL = "virtual"              # Memory C — live virtual trading
    REAL = "real"                    # Memory D — actual broker executions


class ExitReason(str, Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    EXPIRY = "expiry"
    END_OF_DATA = "end_of_data"
    EMERGENCY = "emergency"
    MANUAL = "manual"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Tick:
    time: datetime
    bid: float
    ask: float
    volume: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True)
class Candle:
    time: datetime          # open time of the bar
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread_avg: float = 0.0


@dataclass(frozen=True)
class SymbolSpec:
    """Broker contract specification. Values must come from broker metadata."""

    broker: str
    symbol: str
    digits: int
    point: float
    tick_size: float
    tick_value: float            # account-currency value of one tick for 1.0 lot
    contract_size: float         # ounces per 1.0 lot
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level_points: int = 0  # minimum SL/TP distance in points
    freeze_level_points: int = 0
    swap_long: float = 0.0       # account currency per lot per night (see CostModel)
    swap_short: float = 0.0
    swap_mode: str = "points"    # "points" or "money"
    commission_per_lot_side: float = 0.0  # account currency per lot per side
    margin_initial: float = 0.0
    currency_base: str = "XAU"
    currency_profit: str = "USD"
    trade_mode: str = "full"     # full / closeonly / disabled
    filling_modes: tuple[str, ...] = ()
    execution_mode: str = "market"

    def round_volume(self, lots: float) -> float:
        """Round down to the broker's volume step and clamp to [min, max]. 0 if below min."""
        if lots < self.volume_min:
            return 0.0
        steps = int((lots + 1e-12) / self.volume_step)
        v = round(steps * self.volume_step, 8)
        return min(max(v, self.volume_min), self.volume_max)

    def money_per_price_unit(self, lots: float) -> float:
        """P/L in account currency for a 1.0 price move at `lots`."""
        return lots * self.tick_value / self.tick_size

    @property
    def min_stop_distance(self) -> float:
        return self.stops_level_points * self.point


@dataclass
class TradeProposal:
    side: Side
    entry: float
    stop_loss: float
    take_profit: float
    lots: float
    confidence: float
    valid_until: datetime
    trailing_start: float | None = None   # price distance in profit before trailing activates
    trailing_distance: float | None = None
    expected_cost: float = 0.0
    explanation: str = ""
    strategy_version: str = ""
    model_version: str = ""

    @property
    def risk_reward(self) -> float:
        risk = abs(self.entry - self.stop_loss)
        reward = abs(self.take_profit - self.entry)
        return reward / risk if risk > 0 else 0.0


@dataclass
class Decision:
    side: Side
    confidence: float
    explanation: str
    proposal: TradeProposal | None = None
    features: dict[str, float] = field(default_factory=dict)
    time: datetime = field(default_factory=utcnow)


@dataclass
class SimTrade:
    """A simulated or real trade record, independent of memory domain."""

    trade_id: str
    broker: str
    account: str
    symbol: str
    side: Side
    lots: float
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    strategy_version: str
    model_version: str
    is_estimated_fill: bool = True
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: ExitReason | None = None
    commission: float = 0.0
    swap: float = 0.0
    slippage_cost: float = 0.0
    spread_cost: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    initial_risk_money: float = 0.0
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    context: dict = field(default_factory=dict)
    explanation: str = ""

    @property
    def is_open(self) -> bool:
        return self.exit_time is None

    @property
    def r_multiple(self) -> float:
        return self.net_pnl / self.initial_risk_money if self.initial_risk_money > 0 else 0.0
