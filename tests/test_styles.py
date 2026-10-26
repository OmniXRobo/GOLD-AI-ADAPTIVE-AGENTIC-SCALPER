"""Scalping and swing trade styles: separate engines, memories, signals and promoted strategies."""
import hashlib
import json
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from gold_ai.agents.decision import StrategyParams, style_params
from gold_ai.agents.self_healing import SelfHealingAgent, generate_candidates
from gold_ai.brokers.mock_feed import FakeMT5, synthetic_spec, synthetic_ticks
from gold_ai.brokers.mt5_connector import MT5ReadOnlyConnector
from gold_ai.domain import MemoryDomain, Side, SimTrade, Tick, TradeProposal
from gold_ai.engines.backtest import run_backtest
from gold_ai.engines.live_virtual import LiveVirtualEngine
from gold_ai.market.features import MarketIntelligenceAgent
from gold_ai.notifications.service import SignalService
from gold_ai.notifications.signals import Signal, format_signal
from gold_ai.runtime import build_runtime

BTC = {"name": "BTCUSD.sd", "currency_base": "BTC", "currency_profit": "USD", "description": "Bitcoin vs US Dollar",
       "digits": 2, "point": 0.01, "trade_tick_size": 0.01, "trade_tick_value": 0.01, "trade_contract_size": 1.0}
GOLD = {"name": "XAUUSD.sd", "currency_base": "XAU", "currency_profit": "USD", "trade_contract_size": 100.0}


def test_scalp_strategy_version_unchanged_by_styles():
    # Versions recorded before trade styles existed must keep their id.
    d = asdict(StrategyParams())
    d.pop("style"), d.pop("timeframes")
    old = "strat-" + hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:10]
    assert StrategyParams().version() == old
    swing = style_params("swing")
    assert swing.version() != old and swing.timeframes == ("M15", "H1", "H4")
    assert swing.max_hold_seconds == 3 * 86400 and swing.risk_reward == 2.0
    assert StrategyParams(**{**asdict(swing), "timeframes": ["M15", "H1", "H4"]}).version() == swing.version()


def test_swing_features_use_hourly_bars():
    ticks = list(synthetic_ticks(50_000, start=datetime(2026, 10, 19, tzinfo=timezone.utc), step_seconds=2.0))
    scalp, swing = MarketIntelligenceAgent(), MarketIntelligenceAgent(timeframes=("M15", "H1", "H4"))
    for i, t in enumerate(ticks):
        scalp.on_tick(t)
        swing.on_tick(t)
        if i == 30_000:                # 16.7 h: 20 M5 bars are there, 20 H1 bars are not
            assert scalp.ready and not swing.ready
    a, b = scalp.state(), swing.state()
    assert a.ready and b.ready        # 27.8 h
    assert b.features["atr_m5"] > a.features["atr_m5"] * 2   # hourly ATR is far wider than 5-minute ATR


def test_dashboard_reads_do_not_move_tick_accel():
    m = MarketIntelligenceAgent()
    for t in synthetic_ticks(8_000, start=datetime(2026, 10, 19, tzinfo=timezone.utc), step_seconds=1.0):
        m.on_tick(t)
    first = m.state(advance=True).features["tick_accel"]
    assert m.state().features["tick_accel"] == m.state().features["tick_accel"]
    assert m.state(advance=True).features["tick_accel"] != first or first == 0.0


def test_swing_backtest_records_style_and_longer_trades(settings):
    ticks = list(synthetic_ticks(120_000, start=datetime(2026, 10, 12, tzinfo=timezone.utc), step_seconds=5.0,
                                 regime_switch_every=20_000))
    r = run_backtest(settings, synthetic_spec(), ticks, params=style_params("swing", exploration_rate=0.5))
    assert r.trades, "swing exploration should open trades on 7 days of data"
    assert all(t.context["style"] == "swing" for t in r.trades)
    scalp = run_backtest(settings, synthetic_spec(), ticks, params=StrategyParams(exploration_rate=0.5))
    hold = lambda ts: sum((t.exit_time - t.entry_time).total_seconds() for t in ts) / len(ts)  # noqa: E731
    assert hold(r.trades) > hold(scalp.trades)
    assert max((t.exit_time - t.entry_time).total_seconds() for t in scalp.trades) <= 3600 + 60


def test_self_healing_keeps_swing_hold_time():
    for c in generate_candidates(style_params("swing")):
        assert c.style == "swing" and c.timeframes == ("M15", "H1", "H4")
        assert c.max_hold_seconds >= 4 * 3600


def _rates(start: datetime, n: int, secs: int, price: float = 108_000.0, offset_h: int = 0) -> list[dict]:
    return [{"time": int((start + timedelta(seconds=i * secs)).timestamp()) + offset_h * 3600,
             "open": price + i, "high": price + i + 300, "low": price + i - 300, "close": price + i + 50,
             "tick_volume": 100, "spread": 1500, "real_volume": 0} for i in range(n)]


def test_swing_engine_seeds_broker_bars_and_is_ready_without_days_of_ticks(settings, store):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    h1 = now.replace(minute=0, second=0) - timedelta(hours=100)
    fake = FakeMT5([BTC], {"BTCUSD.sd": Tick(now, 108_000.0, 108_015.0)}, server="Equiti-Demo", company="Equiti",
                   rates={("BTCUSD.sd", FakeMT5.TIMEFRAME_H1): _rates(h1, 100, 3600, offset_h=3),
                          ("BTCUSD.sd", FakeMT5.TIMEFRAME_H4): _rates(h1, 25, 14400, offset_h=3),
                          ("BTCUSD.sd", FakeMT5.TIMEFRAME_M15): _rates(now - timedelta(hours=20), 80, 900,
                                                                       offset_h=3)})
    conn = MT5ReadOnlyConnector(fake, server_utc_offset_hours=3)
    spec = conn.symbol_spec("BTCUSD.sd", "equiti")
    # Only 40 minutes of ticks collected so far (a newly added symbol).
    store.save_ticks("equiti", "BTCUSD.sd", [Tick(t.time, t.mid * 45 - 7.5, t.mid * 45 + 7.5) for t in
                                             synthetic_ticks(2_400, start=now - timedelta(minutes=40))], "mt5")
    eng = LiveVirtualEngine(settings, spec, conn, store, params=style_params("swing"))
    assert eng.key == "virtual:equiti:BTCUSD.sd:swing"
    eng.warm_up(now=now)
    bars = eng.loop.market.mtf.bars["H1"]
    assert len(bars) >= 95 and bars[0].time == h1          # server time converted to UTC
    assert all(b.time.timestamp() + 3600 <= (now - timedelta(minutes=40)).timestamp() + 1 for b in bars[:-2])
    assert eng.loop.market.ready
    assert eng.status()["style"] == "swing" and eng.status()["timeframes"] == ["M15", "H1", "H4"]
    assert fake.order_send_calls == 0


def test_rates_need_known_server_offset():
    fake = FakeMT5([BTC], {}, rates={("BTCUSD.sd", FakeMT5.TIMEFRAME_H1): _rates(datetime(2026, 10, 1,
                                                                                         tzinfo=timezone.utc), 5, 3600)})
    assert MT5ReadOnlyConnector(fake).rates("BTCUSD.sd", "H1") == []   # no live tick yet: offset unknown


def test_styles_keep_separate_memory_and_api_filters(settings, store):
    now = datetime.now(timezone.utc)
    fake = FakeMT5([GOLD, BTC], {"XAUUSD.sd": Tick(now, 4100.0, 4100.2), "BTCUSD.sd": Tick(now, 108_000, 108_015)},
                   server="Equiti-Demo", company="Equiti")
    settings.symbols = ["XAUUSD", "BTCUSD"]
    app, _ = build_runtime(settings, store, use_mt5=True,
                           connector_factory=lambda: MT5ReadOnlyConnector(fake, server_utc_offset_hours=0))
    st = app.state.gold
    scalp, swing = st.virtual_engines["equiti:BTCUSD.sd"], st.virtual_engines["equiti:BTCUSD.sd:swing"]
    assert scalp.loop is not swing.loop and scalp.agent.model is not swing.agent.model
    for i, (eng, style) in enumerate(((scalp, "scalp"), (swing, "swing"))):
        store.save_trade(MemoryDomain.VIRTUAL, SimTrade(
            f"t{i}", "equiti", "v", "BTCUSD.sd", Side.BUY, 0.1, now - timedelta(hours=1), 108_000, 107_000,
            110_000, eng.agent.params.version(), "m", exit_time=now, exit_price=108_500, net_pnl=50.0 * (i + 1),
            context={"style": style}))
    store.save_trade(MemoryDomain.VIRTUAL, SimTrade(       # recorded before styles existed
        "old", "equiti", "v", "BTCUSD.sd", Side.SELL, 0.1, now - timedelta(hours=3), 108_000, 109_000, 106_000,
        "s", "m", exit_time=now - timedelta(hours=2), exit_price=108_100, net_pnl=-10.0))
    st.auth.create_user("owner", "owner-pass-123", "owner")
    c = TestClient(app)
    tok = c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    sw = c.get("/api/trades/virtual?symbol=BTCUSD&style=swing", headers=h).json()
    assert [t["trade_id"] for t in sw["trades"]] == ["t1"] and sw["trades"][0]["style"] == "swing"
    sc = c.get("/api/trades/virtual?symbol=BTCUSD&style=scalp", headers=h).json()
    assert sorted(t["trade_id"] for t in sc["trades"]) == ["old", "t0"]
    assert len(c.get("/api/trades/virtual", headers=h).json()["trades"]) == 3
    assert c.get("/api/trades/virtual?style=hold", headers=h).status_code == 422
    ms = c.get("/api/market/state?symbol=BTCUSD&style=swing", headers=h).json()
    assert ms["style"] == "swing" and ms["timeframes"] == ["M15", "H1", "H4"]
    assert c.get("/api/market/state?symbol=BTCUSD", headers=h).json()["style"] == "scalp"
    ov = c.get("/api/overview", headers=h).json()
    assert sorted(e["style"] for e in ov["virtual_engines"]) == ["scalp", "scalp", "swing", "swing"]
    assert fake.order_send_calls == 0


def test_promoted_strategy_reaches_its_live_engine_and_survives_restart(settings, store):
    now = datetime.now(timezone.utc)
    fake = FakeMT5([GOLD, BTC], {"XAUUSD.sd": Tick(now, 4100.0, 4100.2), "BTCUSD.sd": Tick(now, 108_000, 108_015)},
                   server="Equiti-Demo", company="Equiti")
    settings.symbols = ["XAUUSD", "BTCUSD"]
    factory = lambda: MT5ReadOnlyConnector(fake, server_utc_offset_hours=0)  # noqa: E731
    app, _ = build_runtime(settings, store, use_mt5=True, connector_factory=factory)
    st = app.state.gold
    eng = st.virtual_engines["equiti:BTCUSD.sd:swing"]
    cand = style_params("swing", risk_reward=2.3)
    notes = json.dumps({"broker": "equiti", "symbol": "BTCUSD.sd", "style": "swing"})
    store.register_model("heal-btc-swing", cand.version(), {**asdict(cand), "timeframes": list(cand.timeframes)},
                         {}, stage="validated", notes=notes)
    other = StrategyParams(risk_reward=1.4)
    store.register_model("heal-gold-scalp", other.version(), asdict(other), {}, stage="validated",
                         notes=json.dumps({"broker": "equiti", "symbol": "XAUUSD.sd", "style": "scalp"}))
    st.auth.create_user("owner", "owner-pass-123", "owner")
    c = TestClient(app)
    tok = c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    model_before = eng.agent.model
    # The adaptive family is under investigation (root-cause audit) until the owner closes it.
    r = c.post("/api/models/heal-gold-scalp/promote", headers=h)
    assert r.status_code == 400 and "under investigation" in r.json()["detail"]
    assert c.post("/api/strategies/investigations/close", headers=h,
                  json={"target": "family:adaptive-v1", "reason": "test"}).status_code == 200
    assert c.post("/api/models/heal-gold-scalp/promote", headers=h).status_code == 200
    r = c.post("/api/models/heal-btc-swing/promote", headers=h).json()
    assert r["live_engine"]["applied"] and r["live_engine"]["engine"] == "virtual:equiti:BTCUSD.sd:swing"
    assert eng.agent.params.risk_reward == 2.3 and eng.agent.params.exploration_rate == 0.2
    assert eng.agent.model is model_before                     # learning is kept
    stages = {m["version"]: m["stage"] for m in store.list_models() if m["version"].startswith("heal-")}
    assert stages == {"heal-btc-swing": "approved", "heal-gold-scalp": "approved"}   # scoped per engine
    assert st.virtual_engines["equiti:XAUUSD.sd"].agent.params.risk_reward == 1.4
    assert st.virtual_engines["equiti:BTCUSD.sd"].agent.params.risk_reward == 1.5     # BTC scalping untouched
    app2, _ = build_runtime(settings, store, use_mt5=True, connector_factory=factory)
    assert app2.state.gold.virtual_engines["equiti:BTCUSD.sd:swing"].agent.params.risk_reward == 2.3
    assert fake.order_send_calls == 0


def test_signal_shows_style_and_hold_time():
    now = datetime(2026, 10, 24, 3, tzinfo=timezone.utc)
    p = TradeProposal(Side.BUY, 108_015.0, 107_100.0, 109_845.0, 0.05, 0.62, now + timedelta(minutes=5),
                      style="swing")
    sig = Signal.from_proposal(p, Tick(now, 108_000.0, 108_015.0), "equiti", "BTCUSD.sd", now=now,
                               max_hold_seconds=3 * 86400)
    text = format_signal(sig)
    assert text.splitlines()[1].startswith("SWING BUY BTCUSD.sd") and "holds up to 3 days" in text
    d = sig.to_dict()
    assert d["style"] == "swing" and d["style_label"] == "Swing"
    assert Signal.from_dict(d).style == "swing"
    old = {k: v for k, v in d.items() if k not in ("style", "max_hold_seconds")}   # stored before styles
    assert Signal.from_dict(old).style == "scalp"


def test_concurrent_signals_are_all_kept(settings, store):
    from gold_ai.security.auth import AuthService
    svc = SignalService(store, AuthService(settings, store), [])
    now = datetime.now(timezone.utc)
    p = TradeProposal(Side.BUY, 4100.2, 4095.0, 4108.0, 0.1, 0.6, now + timedelta(minutes=1))
    threads = [threading.Thread(target=svc.create, args=(p, Tick(now, 4100.0, 4100.2), "equiti", f"S{i}"))
               for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(svc.list(limit=100)) == 12


def test_swing_seeding_retried_once_server_offset_is_known(settings, store):
    """Weekend start: the offset is unknown during warm-up, so bars are seeded on a later poll."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    h1 = now.replace(minute=0, second=0) - timedelta(hours=100)
    fake = FakeMT5([BTC], {"BTCUSD.sd": Tick(now, 108_000.0, 108_015.0)}, server="Equiti-Demo", company="Equiti",
                   rates={("BTCUSD.sd", FakeMT5.TIMEFRAME_H1): _rates(h1, 100, 3600),
                          ("BTCUSD.sd", FakeMT5.TIMEFRAME_H4): _rates(h1, 25, 14400),
                          ("BTCUSD.sd", FakeMT5.TIMEFRAME_M15): _rates(now - timedelta(hours=20), 80, 900)})
    conn = MT5ReadOnlyConnector(fake)                      # auto offset: unknown until a quote moves
    spec = conn.symbol_spec("BTCUSD.sd", "equiti")
    store.save_ticks("equiti", "BTCUSD.sd", [Tick(t.time, t.mid * 45 - 7.5, t.mid * 45 + 7.5) for t in
                                             synthetic_ticks(2_400, start=now - timedelta(minutes=40))], "mt5")
    eng = LiveVirtualEngine(settings, spec, conn, store, params=style_params("swing"))
    eng.warm_up(now=now)
    assert not eng.loop.market.ready and len(eng.loop.market.mtf.bars["H1"]) < 5
    conn.server_offset_s = 0                               # another symbol's moving quote measured it
    eng.poll_once()
    assert len(eng.loop.market.mtf.bars["H1"]) >= 95 and eng.loop.market.ready
    assert not eng._seed_pending and fake.order_send_calls == 0
