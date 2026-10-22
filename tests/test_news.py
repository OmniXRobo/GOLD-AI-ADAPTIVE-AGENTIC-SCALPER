import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from gold_ai.brokers.mock_feed import synthetic_spec
from gold_ai.config import RiskConfig
from gold_ai.news import (CalendarFileSource, EconomicEvent, EventClassifier, FieldMapping, HeadlineInterpretation,
                          HttpJsonSource, NewsAgent)
from gold_ai.risk.engine import NewsEvent, RiskEngine

T0 = datetime(2024, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("title,cat,impact", [
    ("Federal Funds Rate", "fomc", "high"),
    ("FOMC Statement", "fomc", "high"),
    ("FOMC Member Waller Speaks", "fed_speech", "medium"),
    ("Fed Chair Powell Testifies", "fed_speech", "medium"),
    ("Core CPI m/m", "cpi", "high"),
    ("PPI m/m", "ppi", "medium"),
    ("Non-Farm Employment Change", "nfp", "high"),
    ("Nonfarm Payrolls", "nfp", "high"),
    ("Unemployment Rate", "unemployment", "high"),
    ("Unemployment Claims", "jobless_claims", "medium"),
    ("Initial Jobless Claims", "jobless_claims", "medium"),
    ("Core PCE Price Index m/m", "pce", "high"),
    ("Advance GDP q/q", "gdp", "medium"),
    ("10-y Bond Auction", "treasury_auction", "low"),
    ("Missile strike reported near border", "geopolitical", "high"),
    ("Pending Home Sales m/m", "other", "low"),
])
def test_classifier_categories(title, cat, impact):
    ev = EventClassifier().classify(EconomicEvent(T0, title, forecast=1.0))
    assert ev.category == cat and ev.impact == impact
    assert 0.0 <= ev.uncertainty <= 1.0


def test_classifier_overrides_provider_impact_and_currency():
    c = EventClassifier()
    # provider rating above the rule is kept; never downgraded
    assert c.classify(EconomicEvent(T0, "PPI m/m", impact="high")).impact == "high"
    # unknown title uses provider impact
    assert c.classify(EconomicEvent(T0, "Mystery Index", impact="medium")).impact == "medium"
    # non-USD data is downgraded one level, geopolitics is not
    assert c.classify(EconomicEvent(T0, "CPI y/y", currency="EUR")).impact == "medium"
    assert c.classify(EconomicEvent(T0, "War escalates", currency="EUR")).impact == "high"
    # missing forecast raises uncertainty
    assert (c.classify(EconomicEvent(T0, "CPI y/y")).uncertainty >
            c.classify(EconomicEvent(T0, "CPI y/y", forecast=0.3)).uncertainty)
    c.add_override(r"ism manufacturing", "other", "high", 0.7)
    ev = c.classify(EconomicEvent(T0, "ISM Manufacturing PMI", forecast=48.5))
    assert ev.impact == "high" and ev.uncertainty == 0.7
    with pytest.raises(ValueError):
        c.add_override("x", "other", "extreme")


def test_csv_calendar_source(tmp_path):
    p = tmp_path / "cal.csv"
    p.write_text("time,title,currency,impact,forecast,previous\n"
                 "2024-06-12T12:30:00Z,Core CPI m/m,USD,High,0.3%,0.3%\n"
                 "2024-06-12 18:00,Federal Funds Rate,USD,,5.50%,5.50%\n"
                 "2024-06-20T12:30:00,Unemployment Claims,USD,Medium,235K,242K\n"
                 "garbage,,,,,\n")
    src = CalendarFileSource(p)
    evs = src.fetch(T0, T0 + timedelta(days=1))
    assert [e.title for e in evs] == ["Core CPI m/m", "Federal Funds Rate"]
    assert evs[0].impact == "high" and evs[0].forecast == 0.3
    assert evs[1].time == datetime(2024, 6, 12, 18, 0, tzinfo=timezone.utc)
    assert src.skipped_rows == 1
    assert len(src.fetch(T0, T0 + timedelta(days=10))) == 3


def test_json_calendar_source_date_time_columns(tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps({"events": [{"date": "2024-06-12", "time": "12:30", "title": "CPI m/m",
                                         "actual": "0.0", "forecast": "0.1"}]}))
    evs = CalendarFileSource(p).fetch(T0, T0 + timedelta(days=1))
    assert evs[0].time.hour == 12 and evs[0].actual == 0.0 and evs[0].currency == "USD"


def test_http_json_source_mapping_and_params():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["params"] = dict(req.url.params)
        seen["auth"] = req.headers.get("x-api-key")
        return httpx.Response(200, json={"data": {"items": [
            {"ts": 1718195400, "name": "Core CPI m/m", "ccy": "USD", "importance": 3, "est": "0.3%"},
            {"ts": "2024-06-12T18:00:00Z", "name": "Federal Funds Rate", "ccy": "USD", "importance": 3},
            {"ts": "not a date", "name": "Broken"},
        ]}})

    src = HttpJsonSource("https://calendar.example/api", items_path="data.items",
                         mapping=FieldMapping(time="ts", title="name", currency="ccy", impact="importance",
                                              forecast="est", previous=None, actual=None),
                         headers={"x-api-key": "k"}, start_param="from", end_param="to",
                         client=httpx.Client(transport=httpx.MockTransport(handler)))
    evs = src.fetch(T0, T0 + timedelta(days=1))
    assert seen == {"params": {"from": "2024-06-12", "to": "2024-06-13"}, "auth": "k"}
    assert [e.title for e in evs] == ["Core CPI m/m", "Federal Funds Rate"]
    assert evs[0].time == datetime(2024, 6, 12, 12, 30, tzinfo=timezone.utc) and evs[0].impact == "high"
    assert src.skipped_items == 1


def test_http_source_error_is_isolated():
    bad = HttpJsonSource("https://x.example", client=httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))), name="bad")

    class Good:
        name = "good"

        def fetch(self, start, end):
            return [EconomicEvent(T0 + timedelta(hours=12), "Core CPI m/m")]

    agent = NewsAgent(sources=[bad, Good()])
    assert agent.refresh(T0, T0 + timedelta(days=1)) == 1
    assert agent.source_errors == {"bad": "HTTPStatusError"}
    assert agent.events[0].category == "cpi"


def test_agent_dedupes_and_feeds_risk_engine():
    cpi = T0 + timedelta(hours=12, minutes=30)
    agent = NewsAgent()
    agent.add_events([EconomicEvent(cpi, "core cpi m/m"), EconomicEvent(cpi, "Core CPI m/m", actual=0.2),
                      EconomicEvent(cpi + timedelta(hours=1), "10-y Bond Auction")])
    assert len(agent.events) == 2 and agent.events[0].actual == 0.2   # later update wins
    risk = agent.risk_events()
    assert all(isinstance(e, NewsEvent) for e in risk)
    assert [e.impact for e in agent.risk_events(min_impact="high")] == ["high"]

    engine = RiskEngine.create(RiskConfig(), synthetic_spec(), 10_000)
    assert agent.sync_risk_engine(engine) == 2
    assert engine.blocked_by_news(cpi - timedelta(minutes=5)).title == "Core CPI m/m"
    assert engine.blocked_by_news(cpi + timedelta(hours=1)) is None   # low-impact auction is not blacked out
    assert [e.title for e in agent.upcoming(T0, min_impact="high")] == ["Core CPI m/m"]


def test_regime_flags_windows():
    cpi = T0 + timedelta(hours=12, minutes=30)
    agent = NewsAgent(pre_event_minutes=30, post_event_minutes=20)
    agent.add_events([EconomicEvent(cpi, "Core CPI m/m"),
                      EconomicEvent(cpi + timedelta(hours=3), "Unemployment Claims")])
    f = agent.regime_flags(cpi - timedelta(minutes=10))
    assert f["news_pre_event_high"] == 1.0 and f["news_post_event_high"] == 0.0
    assert f["news_minutes_to_next_high"] == pytest.approx(10.0)
    assert f["news_window_uncertainty"] > 0.5
    f = agent.regime_flags(cpi + timedelta(minutes=15))
    assert f["news_pre_event_high"] == 0.0 and f["news_post_event_high"] == 1.0
    assert f["news_minutes_since_last_high"] == pytest.approx(15.0)
    f = agent.regime_flags(cpi + timedelta(hours=2, minutes=45))
    assert f["news_pre_event_medium"] == 1.0 and f["news_post_event_high"] == 0.0
    f = NewsAgent().regime_flags(T0)
    assert f["news_pre_event_high"] == 0.0 and f["news_minutes_to_next_high"] == 1440.0


def test_headline_interpreter_optional_and_rate_limited():
    agent = NewsAgent()
    assert asyncio.run(agent.interpret_headlines(["Gold rallies"])) == []   # no-op default

    class Fake:
        calls = 0

        async def interpret(self, headlines):
            Fake.calls += 1
            return [HeadlineInterpretation(h, gold_bias=0.5, confidence=0.6) for h in headlines]

    agent = NewsAgent(interpreter=Fake(), interpret_min_interval_seconds=3600)
    first = asyncio.run(agent.interpret_headlines(["Fed signals cuts"]))
    again = asyncio.run(agent.interpret_headlines(["Another headline"]))
    assert Fake.calls == 1 and first == again and first[0].gold_bias == 0.5

    class Broken:
        async def interpret(self, headlines):
            raise RuntimeError("llm down")

    assert asyncio.run(NewsAgent(interpreter=Broken()).interpret_headlines(["x"])) == []
