from datetime import datetime, timedelta, timezone

from gold_ai.config import RiskConfig
from gold_ai.domain import Side, Tick, TradeProposal
from gold_ai.risk.engine import NewsEvent, RiskEngine

T0 = datetime(2024, 3, 4, 10, tzinfo=timezone.utc)
TICK = Tick(T0, 2400.0, 2400.2)


def prop(**kw):
    d = dict(side=Side.BUY, entry=2400.2, stop_loss=2398.2, take_profit=2403.2, lots=0.05, confidence=0.6,
             valid_until=T0 + timedelta(minutes=1))
    d.update(kw)
    return TradeProposal(**d)


def eng(spec, **cfg):
    e = RiskEngine.create(RiskConfig(**cfg), spec, 10_000)
    e.on_equity(10_000, T0)
    return e


def test_approves_valid(spec):
    v = eng(spec).evaluate(prop(), TICK, 10_000, 0)
    assert v.approved, v.reasons
    assert 0 < v.lots <= 0.10


def test_position_sizing_respects_risk(spec):
    e = eng(spec, risk_per_trade_pct=1.0, max_lots_per_trade=10)
    # 1% of 10k = 100 USD; 2.0 price units * 100 oz/lot = 200 USD/lot -> 0.5 lots
    assert e.position_size(10_000, 2400.2, 2398.2) == 0.5


def test_rejections(spec):
    e = eng(spec)
    assert not e.evaluate(prop(), TICK, 10_000, 1).approved                       # one trade at a time
    assert not e.evaluate(prop(), Tick(T0, 2400, 2401.0), 10_000, 0).approved      # spread 100 pts
    assert not e.evaluate(prop(take_profit=2401.2), TICK, 10_000, 0).approved      # RR 0.5
    assert not e.evaluate(prop(confidence=0.4), TICK, 10_000, 0).approved
    assert not e.evaluate(prop(), TICK, 10_000, 0, now=T0 + timedelta(minutes=5)).approved  # stale
    assert not e.evaluate(prop(side=Side.WAIT), TICK, 10_000, 0).approved


def test_daily_loss_and_drawdown(spec):
    e = eng(spec)
    assert not e.evaluate(prop(), TICK, 9_790, 0).approved  # 2.1% daily loss
    e2 = eng(spec, max_daily_loss_pct=50)
    e2.state.peak_equity = 12_000
    assert not e2.evaluate(prop(), TICK, 10_700, 0).approved  # >10% from peak


def test_news_blackout(spec):
    e = eng(spec)
    e.news = [NewsEvent(T0 + timedelta(minutes=10), "US CPI", "high")]
    v = e.evaluate(prop(), TICK, 10_000, 0)
    assert not v.approved and any("news" in r for r in v.reasons)
    e.news = [NewsEvent(T0 + timedelta(minutes=10), "minor", "low")]
    assert e.evaluate(prop(), TICK, 10_000, 0).approved


def test_emergency_stop_and_sessions(spec):
    e = eng(spec)
    e.trigger_emergency_stop("test")
    assert not e.evaluate(prop(), TICK, 10_000, 0).approved
    e.clear_emergency_stop()
    e.cfg.allowed_sessions_utc = [(12, 20)]
    assert not e.evaluate(prop(), TICK, 10_000, 0).approved


def test_no_martingale_sizing_after_losses(spec):
    e = eng(spec, max_daily_loss_pct=100, max_drawdown_pct=100)
    base = e.position_size(10_000, 2400.2, 2398.2)
    for _ in range(5):
        e.on_trade_closed(-50)
    assert e.position_size(9_750, 2400.2, 2398.2) <= base
