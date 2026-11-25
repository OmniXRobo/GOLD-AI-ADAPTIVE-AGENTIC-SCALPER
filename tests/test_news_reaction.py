from datetime import datetime, timedelta, timezone

from gold_ai.domain import Candle, Side, Tick
from gold_ai.news.events import EconomicEvent
from gold_ai.news.sources import CalendarFileSource
from gold_ai.strategies.setups import NewsReaction, SetupContext

REL = datetime(2026, 11, 25, 13, 30, tzinfo=timezone.utc)


def bars(drift, n=40):
    out, p = [], 3500.0
    for i in range(n):
        t = REL - timedelta(minutes=5 * (n - 8)) + timedelta(minutes=5 * i)
        d = drift if t >= REL else 0.0
        out.append(Candle(t, p, p + 1.0 + max(d, 0), p - 1.0 + min(d, 0), p + d, 100))
        p += d
    return out


def ctx(m5, minutes_after=20):
    now = REL + timedelta(minutes=minutes_after)
    return SetupContext(Tick(now, m5[-1].close, m5[-1].close + 0.2), {"M5": m5}, {}, "x", trigger_tf="M5")


def ev(actual, forecast=0.3, category="cpi", impact="high"):
    return EconomicEvent(REL, "Core CPI m/m", "USD", impact, category, 0.5, forecast, 0.3, actual)


def test_usd_beat_with_gold_falling_sells_once():
    s = NewsReaction()
    s.set_events_provider(lambda: [ev(0.5)])
    m5 = bars(-2.0)
    sig = s.evaluate(ctx(m5))
    assert sig is not None and sig.side == Side.SELL and sig.stop > m5[-1].close
    assert s.evaluate(ctx(m5)) is None                      # one trade per release


def test_no_trade_without_confirmation_surprise_or_outside_window():
    s = NewsReaction()
    s.set_events_provider(lambda: [ev(0.5)])
    assert s.evaluate(ctx(bars(+2.0))) is None             # gold went the other way
    s2 = NewsReaction()
    s2.set_events_provider(lambda: [ev(0.3)])               # in line with forecast
    assert s2.evaluate(ctx(bars(-2.0))) is None
    s3 = NewsReaction()
    s3.set_events_provider(lambda: [ev(0.5)])
    assert s3.evaluate(ctx(bars(-2.0), minutes_after=5)) is None   # inside the blackout minutes
    s4 = NewsReaction()
    s4.set_events_provider(lambda: [ev(0.5, category="fed_speech")])
    assert s4.evaluate(ctx(bars(-2.0))) is None


def test_unemployment_beat_is_usd_negative():
    s = NewsReaction()
    s.set_events_provider(lambda: [EconomicEvent(REL, "Unemployment Rate", "USD", "high", "unemployment", 0.5,
                                                 4.1, 4.1, 4.4)])
    sig = s.evaluate(ctx(bars(+2.0)))
    assert sig is not None and sig.side == Side.BUY


def test_stale_calendar_file_is_reported(tmp_path):
    import os, time
    p = tmp_path / "cal.csv"
    p.write_text("time,title,currency,impact\n2026-11-25T13:30:00Z,CPI,USD,high\n")
    src = CalendarFileSource(p)
    src.fetch(REL - timedelta(days=1), REL + timedelta(days=1))
    assert src.stale_reason is None
    old = time.time() - 3 * 86400
    os.utime(p, (old, old))
    assert len(src.fetch(REL - timedelta(days=1), REL + timedelta(days=1))) == 1
    assert "not updated for 3.0 days" in src.stale_reason


def test_released_events_round_trip_through_persistence():
    from gold_ai.news.agent import NewsAgent
    a = NewsAgent()
    a.add_events([ev(0.5), EconomicEvent(REL + timedelta(days=1), "Retail Sales", "USD", "high", forecast=0.4)])
    recs = a.released_records(REL - timedelta(days=14))
    assert len(recs) == 1                                   # only events with an actual figure
    b = NewsAgent()
    assert b.restore_released(recs) == 1 and b.events[0].actual == 0.5 and b.events[0].time == REL
