from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from gold_ai.api.app import AppState, create_app
from gold_ai.domain import Candle
from gold_ai.market.technical import bollinger, macd, pressure, rsi, stochastic, summary

T0 = datetime(2026, 1, 5, tzinfo=timezone.utc)


def bars_from(closes):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(Candle(T0 + timedelta(hours=i), prev, max(prev, c) + 0.5, min(prev, c) - 0.5, c, 10))
        prev = c
    return out


def test_rsi_extremes_and_reference_value():
    assert rsi(list(range(1, 30))) == 100.0
    assert rsi(list(range(30, 1, -1))) == 0.0
    assert rsi([1.0] * 5) is None
    # Wilder's worked example (StockCharts): first RSI on 15 closes is about 70.46
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    assert abs(rsi(closes) - 70.46) < 0.1


def test_indicators_need_enough_bars():
    b = bars_from([100 + i for i in range(10)])
    s = summary(b, "H1")
    assert s["rsi14"] is None and s["macd"] is None and s["ma50"] is None
    assert s["label"] == "insufficient data" and s["score"] is None
    assert s["bars_missing"]["ma200"] == 190


def test_uptrend_reads_bullish_and_downtrend_bearish():
    up = bars_from([2000 + i * 2 + (i % 3) for i in range(220)])
    s = summary(up, "H1")
    assert s["label"] in ("bullish", "strong bullish") and s["score"] > 0
    assert s["pressure"]["buy_pct"] > 50
    down = bars_from([3000 - i * 2 - (i % 3) for i in range(220)])
    assert summary(down, "H1")["score"] < 0


def test_component_shapes():
    closes = [2000 + (i % 7) for i in range(60)]
    b = bars_from(closes)
    m = macd(closes)
    assert set(m) == {"macd", "signal", "histogram"}
    st = stochastic(b)
    assert 0 <= st["k"] <= 100 and 0 <= st["d"] <= 100
    bb = bollinger(closes)
    assert bb["lower"] < bb["middle"] < bb["upper"]
    assert pressure(b[:5]) is None


def test_technical_endpoint(settings, store):
    st = AppState(settings, store)
    st.auth.create_user("owner", "owner-pass-123", "owner")
    c = TestClient(create_app(st))
    h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]}
    assert c.get("/api/analysis/technical", headers=h).status_code == 503
    eng = SimpleNamespace(spec=SimpleNamespace(broker="equiti", symbol="XAUUSD.sd"),
                          loop=SimpleNamespace(market=SimpleNamespace(mtf=SimpleNamespace(bars={"H1": bars_from([2000 + i for i in range(40)])}))))
    st.virtual_engines["e"] = eng
    r = c.get("/api/analysis/technical?tf=H1", headers=h).json()
    assert r["symbol"] == "XAUUSD.sd" and r["bars"] == 40 and r["rsi14"] == 100.0
    assert c.get("/api/analysis/technical?tf=W9", headers=h).status_code == 422
