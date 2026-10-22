from datetime import datetime, timedelta, timezone

from gold_ai.config import CostConfig
from gold_ai.costs import CostModel
from gold_ai.domain import ExitReason, Side, Tick, TradeProposal
from gold_ai.engines.simulator import PositionSimulator

T0 = datetime(2024, 3, 4, 10, tzinfo=timezone.utc)  # Monday


def tk(sec, bid, spread=0.2):
    return Tick(T0 + timedelta(seconds=sec), bid, round(bid + spread, 2))


def mk(spec, slip=0, stop_extra=0):
    return CostModel(spec, CostConfig(slippage_points_entry=slip, slippage_points_exit=slip,
                                      stop_slippage_extra_points=stop_extra))


def prop(side, entry, sl, tp, lots=1.0, **kw):
    return TradeProposal(side, entry, sl, tp, lots, 0.6, T0 + timedelta(hours=1), **kw)


def test_spread_commission_and_fills(spec):
    cm = mk(spec, slip=5)
    t = tk(0, 2400.00)
    assert abs(cm.entry_fill(Side.BUY, t) - 2400.25) < 1e-9   # ask + 5 points
    assert abs(cm.entry_fill(Side.SELL, t) - 2399.95) < 1e-9
    assert cm.commission(1.0) == 7.0
    assert abs(cm.spread_cost(1.0, t) - 20.0) < 1e-9          # 0.20 * 100 oz


def test_swap_triple_wednesday(spec):
    cm = mk(spec)
    tue = datetime(2024, 3, 5, 12, tzinfo=timezone.utc)
    thu = datetime(2024, 3, 7, 12, tzinfo=timezone.utc)
    # Tue->Wed (1) + Wed->Thu (triple = 3) = 4 units; -50 points * 0.01 * 100 = -50/unit
    assert abs(cm.swap(Side.BUY, 1.0, tue, thu) - (-200.0)) < 1e-9
    assert abs(cm.swap(Side.SELL, 1.0, tue, thu) - 80.0) < 1e-9
    assert cm.swap(Side.BUY, 1.0, tue, tue + timedelta(hours=3)) == 0


def test_take_profit_buy(spec):
    sim = PositionSimulator(mk(spec), "mock", "a")
    t = sim.open(prop(Side.BUY, 2400.2, 2399.0, 2402.0), tk(0, 2400.0))
    assert t.entry_price == 2400.2
    assert sim.on_tick(tk(1, 2401.9)) == []
    done = sim.on_tick(tk(2, 2402.05))
    assert done[0].exit_reason == ExitReason.TAKE_PROFIT and done[0].exit_price == 2402.0
    assert abs(done[0].gross_pnl - 180.0) < 1e-6
    assert abs(done[0].net_pnl - (180.0 - 7.0)) < 1e-6


def test_stop_loss_sell_uses_ask_and_gap(spec):
    sim = PositionSimulator(mk(spec), "mock", "a")
    sim.open(prop(Side.SELL, 2400.0, 2401.0, 2398.0), tk(0, 2400.0))
    # Ask = 2401.5 gaps through SL 2401 -> fill at market (worse), not at SL.
    done = sim.on_tick(tk(1, 2401.3))
    assert done[0].exit_reason == ExitReason.STOP_LOSS
    assert abs(done[0].exit_price - 2401.5) < 1e-9


def test_buy_stop_triggers_on_bid(spec):
    sim = PositionSimulator(mk(spec), "mock", "a")
    sim.open(prop(Side.BUY, 2400.2, 2400.1 - 0.5, 2400.2 + 0.3), tk(0, 2400.0))
    done = sim.on_tick(tk(1, 2399.0))
    assert done[0].exit_reason == ExitReason.STOP_LOSS


def test_trailing_stop_only_tightens(spec):
    sim = PositionSimulator(mk(spec), "mock", "a")
    sim.open(prop(Side.BUY, 2400.2, 2399.0, 2410.0, trailing_start=1.0, trailing_distance=0.5), tk(0, 2400.0))
    sim.on_tick(tk(1, 2401.5))     # +1.3 -> trail to 2401.0
    assert abs(sim.positions[0].current_sl - 2401.0) < 1e-9
    sim.on_tick(tk(2, 2401.2))     # pullback must not loosen
    assert abs(sim.positions[0].current_sl - 2401.0) < 1e-9
    done = sim.on_tick(tk(3, 2400.9))
    assert done[0].exit_reason == ExitReason.TRAILING_STOP and done[0].net_pnl > 0


def test_one_position_limit_and_invalid_stops(spec):
    sim = PositionSimulator(mk(spec), "mock", "a", max_open=1)
    assert sim.open(prop(Side.BUY, 2400.2, 2399.0, 2402.0), tk(0, 2400.0))
    assert sim.open(prop(Side.BUY, 2400.2, 2399.0, 2402.0), tk(1, 2400.0)) is None
    sim2 = PositionSimulator(mk(spec), "mock", "a")
    # SL inside broker stop level (20 points = 0.20) -> rejected
    assert sim2.open(prop(Side.BUY, 2400.2, 2400.1, 2402.0), tk(0, 2400.0)) is None


def test_expiry(spec):
    sim = PositionSimulator(mk(spec), "mock", "a", max_hold_seconds=60)
    sim.open(prop(Side.BUY, 2400.2, 2399.0, 2402.0), tk(0, 2400.0))
    assert sim.on_tick(tk(30, 2400.1)) == []
    assert sim.on_tick(tk(61, 2400.1))[0].exit_reason == ExitReason.EXPIRY
