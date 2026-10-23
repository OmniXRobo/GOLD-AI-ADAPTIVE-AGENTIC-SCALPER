from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from gold_ai.brokers.mock_feed import FakeMT5
from gold_ai.brokers.mt5_connector import MT5ReadOnlyConnector
from gold_ai.brokers.symbols import discover_instrument
from gold_ai.costs import CostModel
from gold_ai.domain import MemoryDomain, Side, SimTrade, SymbolSpec, Tick, TradeProposal
from gold_ai.instruments import INSTRUMENTS, canonical, instrument_for, settings_for, suffix_of
from gold_ai.notifications.signals import Signal, format_signal
from gold_ai.risk.engine import NewsEvent, RiskEngine
from gold_ai.runtime import build_runtime

FX = dict(digits=5, point=0.00001, trade_tick_size=0.00001, trade_tick_value=1.0, trade_contract_size=100000.0)
JPY = dict(digits=3, point=0.001, trade_tick_size=0.001, trade_tick_value=0.67, trade_contract_size=100000.0)
BTC = dict(digits=2, point=0.01, trade_tick_size=0.01, trade_tick_value=0.01, trade_contract_size=1.0)

SYMS = [
    {"name": "XAUUSD.sd", "currency_base": "XAU", "currency_profit": "USD", "trade_contract_size": 100.0},
    {"name": "EURUSD", "currency_base": "EUR", "currency_profit": "USD", **FX},
    {"name": "EURUSD.sd", "currency_base": "EUR", "currency_profit": "USD", **FX},
    {"name": "EURGBP.sd", "currency_base": "EUR", "currency_profit": "GBP", **FX},
    {"name": "USDJPY.sd", "currency_base": "USD", "currency_profit": "JPY", **JPY},
    {"name": "BTCUSD.sd", "currency_base": "USD", "currency_profit": "USD", "description": "Bitcoin vs US Dollar",
     **BTC},
]


def fx_spec(symbol="EURUSD.sd", **kw):
    d = dict(broker="equiti", symbol=symbol, digits=5, point=0.00001, tick_size=0.00001, tick_value=1.0,
             contract_size=100000.0, volume_min=0.01, volume_max=100.0, volume_step=0.01,
             currency_base="EUR", currency_profit="USD")
    d.update(kw)
    return SymbolSpec(**d)


def test_canonical_names_and_suffixes():
    assert canonical("XAUUSD.sd") == "XAUUSD" and canonical("GOLD") == "XAUUSD"
    assert canonical("EURUSDm") == "EURUSD" and canonical("usdjpy.a") == "USDJPY"
    assert canonical("BTCUSD") == "BTCUSD" and canonical("EURGBP") is None
    assert suffix_of("XAUUSD.sd") == ".sd" and suffix_of("EURUSDm") == "m" and suffix_of("GOLD") == ""
    assert set(INSTRUMENTS) == {"XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD",
                                "USDCAD", "NZDUSD"}
    assert INSTRUMENTS["USDJPY"].pip_size == 0.01 and INSTRUMENTS["EURUSD"].pip_size == 0.0001


def test_discovery_validates_currencies_and_prefers_gold_suffix():
    assert discover_instrument(SYMS, "EURUSD", ".sd")[0].name == "EURUSD.sd"
    assert [c.name for c in discover_instrument(SYMS, "EURUSD")][:1] == ["EURUSD"]
    assert discover_instrument(SYMS, "GBPUSD") == []
    bad = [{"name": "EURUSD.x", "currency_base": "EUR", "currency_profit": "JPY"}]
    assert discover_instrument(bad, "EURUSD") == []
    # crypto CFDs that report a USD base are accepted only when the description names the coin
    assert discover_instrument(SYMS, "BTCUSD")[0].name == "BTCUSD.sd"
    assert discover_instrument([{"name": "BTCUSD", "currency_base": "USD", "currency_profit": "USD"}], "BTCUSD") == []


def test_settings_for_converts_pips_to_points(settings):
    s = settings_for(settings, fx_spec())
    assert s.risk.max_spread_points == 20             # 2.0 pips at 5 digits
    assert s.costs.slippage_points_entry == 2
    assert s.risk.news_currencies == ["EUR", "USD"]
    assert (6.0, 20.75) in s.risk.allowed_sessions_utc
    gold = settings_for(settings, fx_spec("XAUUSD.sd", digits=2, point=0.01, tick_size=0.01))
    assert gold.risk == settings.risk and gold.costs == settings.costs
    settings.instrument_overrides = {"EURUSD": {"max_spread_pips": 1.0, "sessions_utc": [[0, 24]]}}
    s = settings_for(settings, fx_spec())
    assert s.risk.max_spread_points == 10 and s.risk.allowed_sessions_utc == [(0, 24)]
    btc = settings_for(settings, fx_spec("BTCUSD.sd", digits=2, point=0.01, tick_size=0.01))
    assert btc.risk.max_spread_points == 6000 and btc.costs.triple_swap_weekday is None


def test_news_blackout_only_for_pair_currencies(settings):
    s = settings_for(settings, fx_spec())
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    r = RiskEngine.create(s.risk, fx_spec(), 10_000)
    r.news = [NewsEvent(now, "BoJ rate decision", "high", "JPY")]
    assert r.blocked_by_news(now) is None
    r.news.append(NewsEvent(now, "ECB rate decision", "high", "EUR"))
    assert r.blocked_by_news(now).title == "ECB rate decision"


def test_crypto_swap_has_no_triple_day(settings):
    spec = fx_spec("BTCUSD.sd", digits=2, point=0.01, tick_size=0.01, tick_value=0.01, contract_size=1.0,
                   swap_mode="money", swap_long=-10.0, swap_short=-10.0)
    s = settings_for(settings, spec)
    tue = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)   # crosses Wednesday's rollover
    assert CostModel(spec, s.costs).swap(Side.BUY, 1.0, tue, tue + timedelta(days=2)) == -20.0
    assert CostModel(spec, settings.costs).swap(Side.BUY, 1.0, tue, tue + timedelta(days=2)) == -40.0


def test_signal_text_uses_symbol_digits_and_pips():
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    p = TradeProposal(Side.BUY, 1.08512, 1.08362, 1.08737, 0.1, 0.6, now + timedelta(minutes=1))
    sig = Signal.from_proposal(p, Tick(now, 1.08510, 1.08512), "equiti", "EURUSD.sd", now=now)
    text = format_signal(sig)
    assert "@ 1.08512" in text and "SL 1.08362 (15.0 pips)" in text and "(22.5 pips)" in text
    d = sig.to_dict()
    assert d["instrument"] == "EURUSD" and d["digits"] == 5 and round(d["sl_pips"], 1) == 15.0
    assert Signal.from_dict(d).symbol == "EURUSD.sd"


def test_runtime_runs_one_engine_per_instrument(settings, store):
    now = datetime.now(timezone.utc)
    ticks = {"XAUUSD.sd": Tick(now, 4100.0, 4100.2), "EURUSD.sd": Tick(now, 1.085, 1.08502),
             "USDJPY.sd": Tick(now, 151.2, 151.21), "BTCUSD.sd": Tick(now, 108000.0, 108015.0)}
    fake = FakeMT5(SYMS, ticks, server="Equiti-Demo", company="Equiti")
    app, supervisor = build_runtime(settings, store, use_mt5=True,
                                    connector_factory=lambda: MT5ReadOnlyConnector(fake, server_utc_offset_hours=0))
    st = app.state.gold
    assert [e.spec.symbol for e in st.virtual_engines.values()] == ["XAUUSD.sd", "BTCUSD.sd", "EURUSD.sd",
                                                                     "USDJPY.sd"]
    assert {"collector", "live_virtual", "collector:EURUSD.sd", "live_virtual:BTCUSD.sd"} <= set(supervisor.status())
    eur = st.virtual_engines["equiti:EURUSD.sd"]
    assert eur.key == "virtual:equiti:EURUSD.sd" and eur.loop.risk.cfg.max_spread_points == 20
    assert eur.poll_once() is not None

    # each instrument's trades stay apart in Memory C
    for sym in ("EURUSD.sd", "XAUUSD.sd"):
        store.save_trade(MemoryDomain.VIRTUAL, SimTrade(
            f"t-{sym}", "equiti", "v", sym, Side.BUY, 0.1, now - timedelta(minutes=5), 1.085, 1.084, 1.087,
            "s", "m", exit_time=now, exit_price=1.086, net_pnl=10.0))
    st.auth.create_user("owner", "owner-pass-123", "owner")
    c = TestClient(app)
    tok = c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    inst = c.get("/api/instruments", headers=h).json()
    assert [i["instrument"] for i in inst] == ["XAUUSD", "BTCUSD", "EURUSD", "USDJPY"]
    assert inst[2]["pip_size"] == 0.0001 and inst[2]["digits"] == 5
    rows = c.get("/api/trades/virtual?symbol=EURUSD", headers=h).json()["trades"]
    assert [r["symbol"] for r in rows] == ["EURUSD.sd"] and rows[0]["pip_size"] == 0.0001
    assert c.get("/api/market/state?symbol=USDJPY", headers=h).json()["symbol"] == "USDJPY.sd"
    assert c.get("/api/market/state?symbol=GBPUSD", headers=h).status_code == 404
    assert fake.order_send_calls == 0


def test_runtime_symbols_setting_limits_instruments(settings, store):
    settings.symbols = ["EURUSD"]
    fake = FakeMT5(SYMS, {}, server="Equiti-Demo", company="Equiti")
    app, _ = build_runtime(settings, store, use_mt5=True,
                           connector_factory=lambda: MT5ReadOnlyConnector(fake, server_utc_offset_hours=0))
    assert list(app.state.gold.virtual_engines) == ["equiti:EURUSD"]   # no gold suffix to prefer
    assert instrument_for("EURUSD").name == "EURUSD"


def test_backtest_uses_instrument_spread_limit(settings):
    from gold_ai.agents.decision import StrategyParams
    from gold_ai.brokers.mock_feed import synthetic_ticks
    from gold_ai.engines.backtest import run_backtest
    spec = fx_spec("BTCUSD.sd", digits=2, point=0.01, tick_size=0.01, tick_value=0.01, contract_size=1.0,
                   currency_base="BTC")
    start = datetime(2026, 10, 19, 7, tzinfo=timezone.utc)
    ticks = [Tick(t.time, t.mid * 45 - 7.5, t.mid * 45 + 7.5)   # synthetic, $15 spread
             for t in synthetic_ticks(20_000, start=start, step_seconds=0.5)]
    r = run_backtest(settings, spec, ticks, params=StrategyParams(exploration_rate=0.3))
    assert not any(k.startswith("spread") for k in r.stats.rejection_reasons)


def test_offset_remeasured_per_symbol_while_bitcoin_streams():
    conn = MT5ReadOnlyConnector(FakeMT5(SYMS))
    t0 = 1_800_000_000.0
    conn._observe_offset("XAUUSD.sd", int((t0 + 3 * 3600) * 1000), now=t0)
    conn._observe_offset("XAUUSD.sd", int((t0 + 3 * 3600 + 1) * 1000), now=t0 + 1)
    assert conn.server_offset_s == 3 * 3600
    t = t0
    for i in range(1, 200):            # Bitcoin keeps quoting every minute through the weekend
        t = t0 + i * 60
        conn._observe_offset("BTCUSD.sd", int((t + 3 * 3600) * 1000 + i), now=t)
    # gold resumes after its pause with the server clock moved back an hour (daylight-saving end)
    conn._observe_offset("XAUUSD.sd", int((t + 2 * 3600) * 1000), now=t)
    assert conn.server_offset_s == 2 * 3600
