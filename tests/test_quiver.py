from datetime import datetime, timedelta, timezone

import httpx
import pytest

from gold_ai.altdata import QuiverAgent, QuiverClient, QuiverConfig, parse_congress, parse_offexchange
from gold_ai.altdata.quiver import NEUTRAL

NOW = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)


def day(n):
    return (NOW - timedelta(days=n)).date().isoformat()


def make_agent(routes, cfg=None):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        body = routes.get(req.url.path)
        if body is None:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=body)

    client = QuiverClient("tok-123", client=httpx.Client(transport=httpx.MockTransport(handler)))
    return QuiverAgent(client, cfg or QuiverConfig(offexchange_tickers=["GLD"], congress_tickers=["GLD"])), calls


def test_no_token_is_unavailable_and_neutral():
    agent = QuiverAgent()
    assert agent.refresh(NOW) == 0
    f = agent.features(NOW)
    assert f.available is False and f.sources == []
    assert all(f.values[k] == v for k, v in NEUTRAL.items())
    assert f.values["alt_offex_available"] == 0.0 and f.values["alt_congress_available"] == 0.0
    with pytest.raises(ValueError):
        QuiverClient("")


def test_parsers_skip_bad_rows():
    off = parse_offexchange("gld", [{"Date": "2026-10-20", "OTC_Short": "1,000", "OTC_Total": 4000},
                                    {"Date": "bad", "OTC_Short": 1, "OTC_Total": 2}, {"Date": "2026-10-21"}])
    assert len(off) == 1 and off[0].ticker == "GLD" and off[0].short_ratio == 0.25
    cg = parse_congress("GLD", [{"ReportDate": "2026-10-01", "Transaction": "Purchase", "Representative": "A"},
                                {"ReportDate": "2026-10-02", "Transaction": "Sale (Partial)"},
                                {"ReportDate": "2026-10-03", "Transaction": "Exchange"},
                                {"Transaction": "Purchase"}])
    assert [t.side for t in cg] == ["buy", "sell"]


def test_features_use_only_published_data_and_bearer_token():
    off = [{"Date": day(i), "OTC_Short": 400 + (i % 5) * 10, "OTC_Total": 1000} for i in range(1, 40)]
    off.append({"Date": day(0), "OTC_Short": 900, "OTC_Total": 1000})   # today's row: not public yet
    cg = [{"ReportDate": day(5), "TransactionDate": day(40), "Transaction": "Purchase"},
          {"ReportDate": day(10), "Transaction": "Purchase"},
          {"ReportDate": day(12), "Transaction": "Sale"},
          {"ReportDate": day(60), "Transaction": "Sale"},          # outside 30-day window
          {"ReportDate": (NOW + timedelta(days=1)).date().isoformat(), "Transaction": "Sale"}]   # future
    agent, calls = make_agent({"/beta/historical/offexchange/GLD": off, "/beta/historical/congresstrading/GLD": cg})
    assert agent.refresh(NOW) == len(off) + len(cg)
    assert all(c.headers["Authorization"] == "Bearer tok-123" for c in calls)
    f = agent.features(NOW)
    assert f.available and set(f.sources) == {"offexchange", "congress"}
    assert f.values["alt_etf_offex_short_ratio"] == pytest.approx(0.41)   # day 1, not today's 0.9
    assert f.as_of["offexchange"] == day(1)
    assert abs(f.values["alt_etf_offex_short_z"]) < 3
    assert f.values["alt_congress_gold_trades_30d"] == 3.0 and f.values["alt_congress_gold_net_30d"] == 1.0
    assert f.as_of["congress"] == day(5)


def test_failing_endpoint_is_recorded_not_raised():
    agent, _ = make_agent({"/beta/historical/congresstrading/GLD": []})
    agent.refresh(NOW)
    assert agent.source_errors == {"offexchange:GLD": "HTTPStatusError 404"}
    f = agent.features(NOW)
    assert f.values["alt_offex_available"] == 0.0 and f.values["alt_etf_offex_short_ratio"] == 0.5
