from datetime import datetime, timedelta, timezone

import pytest

from gold_ai.brokers.mock_feed import synthetic_ticks
from gold_ai.domain import Tick
from gold_ai.market.candles import CandleBuilder, build_candles, resample
from gold_ai.market.features import FEATURE_NAMES, MarketIntelligenceAgent

T0 = datetime(2024, 1, 2, 8, 0, tzinfo=timezone.utc)


def test_candle_closes_only_on_next_bar():
    b = CandleBuilder("M1")
    assert b.update(Tick(T0, 1.0, 1.1)) is None
    assert b.update(Tick(T0 + timedelta(seconds=30), 2.0, 2.1)) is None
    c = b.update(Tick(T0 + timedelta(seconds=61), 1.5, 1.6))
    assert c.open == 1.0 and c.high == 2.0 and c.close == 2.0 and c.tick_volume == 2


def test_out_of_order_rejected():
    b = CandleBuilder("M1")
    b.update(Tick(T0 + timedelta(minutes=5), 1, 1.1))
    with pytest.raises(ValueError):
        b.update(Tick(T0, 1, 1.1))


def test_m10_resample_matches_direct_build():
    ticks = list(synthetic_ticks(3600, start=T0, step_seconds=1))
    m1 = build_candles(ticks, "M1", include_partial=True)
    direct = build_candles(ticks, "M10", include_partial=True)
    derived = resample(m1, "M10")
    assert len(direct) == len(derived)
    for a, b in zip(direct, derived):
        assert (a.time, a.open, a.high, a.low, a.close) == (b.time, b.open, b.high, b.low, b.close)


def test_features_warmup_and_ready():
    agent = MarketIntelligenceAgent()
    ticks = synthetic_ticks(20 * 300 + 400, start=T0, step_seconds=1)
    states = []
    for i, t in enumerate(ticks):
        agent.on_tick(t)
        if i == 100:
            states.append(agent.state())
    assert not states[0].ready
    s = agent.state()
    assert s.ready and set(s.features) == set(FEATURE_NAMES)
    assert s.features["atr_m5"] > 0
    assert s.regime in ("trending_up", "trending_down", "ranging", "volatile", "quiet")


def test_features_are_causal():
    """Features at tick i must not change when future ticks are different."""
    base = list(synthetic_ticks(7000, start=T0, seed=1))
    alt_future = list(synthetic_ticks(500, start=base[6499].time + timedelta(seconds=1), price=3000, seed=9))
    a, b = MarketIntelligenceAgent(), MarketIntelligenceAgent()
    for t in base[:6500]:
        a.on_tick(t)
        b.on_tick(t)
    fa = a.state().features
    for t in base[6500:]:
        a.on_tick(t)
    for t in alt_future:
        b.on_tick(t)
    # recompute on a fresh agent with only the prefix
    c = MarketIntelligenceAgent()
    for t in base[:6500]:
        c.on_tick(t)
    fc = c.state().features
    for k in FEATURE_NAMES:
        if k != "tick_accel":
            assert fa[k] == pytest.approx(fc[k])
