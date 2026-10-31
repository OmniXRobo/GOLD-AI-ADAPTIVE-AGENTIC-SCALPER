"""Indicator library, strategy setups, research harness and feature evaluation.

All data here is synthetic (gold_ai.brokers.mock_feed) and says nothing about real markets."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from gold_ai.agents.decision import ModelState, StrategyParams, TradingDecisionAgent
from gold_ai.brokers.mock_feed import SYNTHETIC_SOURCE, synthetic_ticks
from gold_ai.domain import Candle, MemoryDomain, Side, Tick
from gold_ai.market.features import FEATURE_NAMES, MarketState
from gold_ai.market.indicators import (adx, bollinger_stats, detect_sweep, ema, swing_points, tick_volume_profile,
                                       tick_vwap)
from gold_ai.research.features import FeatureEvalConfig, bracket_outcome, evaluate_features
from gold_ai.research.setup_eval import (ResearchConfig, evaluate_setups, run_lanes, run_rules, to_markdown,
                                         verdict)
from gold_ai.research.stats import bootstrap_ci, r_summary, spearman
from gold_ai.strategies.agent import RuleAgent, RuleParams
from gold_ai.strategies.setups import FailedBreakout, LiquiditySweep, SetupContext

T0 = datetime(2024, 1, 2, 8, tzinfo=timezone.utc)


def bar(i, o, h, lo, c, v=10, tf=60, sp=0.2):
    return Candle(T0 + timedelta(seconds=tf * i), o, h, lo, c, v, sp)


def ticks(n=60_000, seed=3, drift=0.0):
    return list(synthetic_ticks(n, step_seconds=2, seed=seed, drift=drift, regime_switch_every=6000))


# -- indicators -------------------------------------------------------------------------------------------

def test_ema_matches_hand_computation():
    vals = [1, 2, 3, 4, 5, 6]
    k = 2 / 4
    e = sum(vals[:3]) / 3
    for v in vals[3:]:
        e = v * k + e * (1 - k)
    assert ema(vals, 3) == pytest.approx(e)
    assert ema(vals[:2], 3) is None


def test_adx_trend_vs_chop():
    up = [bar(i, 100 + i, 100.8 + i, 99.9 + i, 100.7 + i) for i in range(40)]
    d = adx(up)
    assert d["plus_di"] > d["minus_di"] and d["adx"] > 50
    chop = [bar(i, 100, 101, 99, 100.5 if i % 2 else 99.5) for i in range(40)]
    assert adx(chop)["adx"] < 20
    assert adx(up[:20]) is None


def test_bollinger_stats_bounds():
    closes = [100 + (i % 5) * 0.1 for i in range(120)]
    bb = bollinger_stats(closes)
    assert bb["lower"] < bb["middle"] < bb["upper"]
    assert 0 <= bb["pct_b"] <= 1 and 0 <= bb["bandwidth_pctile"] <= 1


def test_tick_vwap_is_tick_volume_weighted():
    bars = [bar(0, 10, 12, 8, 10, v=1), bar(1, 20, 22, 18, 20, v=3)]
    assert tick_vwap(bars, T0) == pytest.approx((10 * 1 + 20 * 3) / 4)
    assert tick_vwap(bars, T0 + timedelta(minutes=1)) == pytest.approx(20)


def test_volume_profile_poc_in_heavy_bar():
    bars = [bar(0, 100, 101, 99, 100, v=1), bar(1, 105, 106, 104, 105, v=50), bar(2, 110, 111, 109, 110, v=1)]
    vp = tick_volume_profile(bars, bins=12)
    assert 104 <= vp["poc"] <= 106 and "tick-volume" in vp["label"]


def test_swing_points_need_right_side_confirmation():
    highs = [1, 2, 3, 9, 3, 2, 1, 2, 3, 10]
    bars = [bar(i, h - 0.5, h, h - 1, h - 0.5) for i, h in enumerate(highs)]
    hs = [s for s in swing_points(bars, 3, 3) if s.kind == "high"]
    assert [s.index for s in hs] == [3]       # the last bar (10) is not confirmed yet: no look-ahead


def _sweep_bars():
    # swing low at index 5 (98.0), then a bar wicks to 97.5 and closes back above 98
    lows = [100, 99.6, 99.2, 98.8, 98.4, 98.0, 98.5, 98.9, 99.2, 99.4, 99.5, 99.6]
    bars = [bar(i, lo + 0.5, lo + 1.0, lo, lo + 0.6) for i, lo in enumerate(lows)]
    bars.append(bar(len(lows), 99.0, 99.6, 97.5, 98.6))
    return bars


def test_detect_liquidity_sweep():
    sw = detect_sweep(_sweep_bars(), 3, 3)
    assert sw is not None and sw.side == "BUY" and sw.level == 98.0 and sw.extreme == 97.5
    no = _sweep_bars()[:-1] + [bar(12, 99.0, 99.6, 98.2, 99.1)]   # did not trade below the swing
    assert detect_sweep(no, 3, 3) is None


# -- setups and rule agent ----------------------------------------------------------------------------------

def _ctx(m1, a5_bars=None):
    m5 = a5_bars or [bar(i, 100, 101, 99, 100, tf=300) for i in range(30)]   # ATR(M5) = 2.0
    last = m1[-1]
    return SetupContext(Tick(last.time + timedelta(seconds=60), last.close, last.close + 0.2), {"M1": m1, "M5": m5},
                        {}, "ranging")


def test_liquidity_sweep_setup_stop_beyond_wick():
    sig = LiquiditySweep(left=3, right=3, min_wick_atr=0.1).evaluate(_ctx(_sweep_bars()))
    assert sig is not None and sig.side == Side.BUY and sig.stop < 97.5


def test_failed_breakout_setup():
    box = [bar(i, 100, 101, 99, 100.2) for i in range(61)]
    recent = [bar(61, 100.5, 101.8, 100.4, 101.5), bar(62, 101.5, 101.6, 100.6, 101.2), bar(63, 101.2, 101.3, 100.1, 100.3)]
    sig = FailedBreakout(range_m1=60, k=3).evaluate(_ctx(box + recent))
    assert sig is not None and sig.side == Side.SELL and sig.stop > 101.8


def test_rule_agent_is_simulation_only():
    st = MarketState(dict.fromkeys(FEATURE_NAMES, 0.0), "ranging", True, Tick(T0, 100, 100.2), {"M1": _sweep_bars()})
    d = RuleAgent(RuleParams(setup="liquidity_sweep")).decide(st, 10_000, lambda e, s: 0.1, lambda lots: 1.0, False)
    assert d.side == Side.WAIT and d.explanation.startswith("NO TRADE")


# -- harness -------------------------------------------------------------------------------------------------

def test_research_is_causal_no_lookahead(settings, spec):
    tk = ticks(40_000)
    cut = tk[25_000].time
    short, _ = run_rules(settings, spec, tk[:25_000], RuleParams(setup="legacy_momentum"))
    full, _ = run_rules(settings, spec, tk, RuleParams(setup="legacy_momentum"))
    done = lambda ts: [(t.entry_time, t.side, round(t.net_pnl, 6)) for t in ts if t.exit_time < cut]  # noqa: E731
    assert done(short) and done(short) == done(full)


def test_lanes_are_independent(settings, spec):
    tk = ticks(30_000)
    alone, _ = run_rules(settings, spec, tk, RuleParams(setup="legacy_momentum", risk_reward=1.5))
    lanes = run_lanes(settings, spec, tk, [(RuleParams(setup="breakout"), None),
                                           (RuleParams(setup="legacy_momentum", risk_reward=1.5), None)])
    assert [round(t.net_pnl, 6) for t in lanes[1][0]] == [round(t.net_pnl, 6) for t in alone]


def test_research_trades_obey_risk_and_fill_next_tick(settings, spec):
    tk = ticks(40_000)
    trades, _ = run_rules(settings, spec, tk, RuleParams(setup="legacy_momentum"))
    times = [t.time for t in tk]
    assert trades
    for t in trades:
        assert t.context["setup"] == "legacy_momentum" and t.context["exploration"] is True
        assert t.entry_time in times and t.initial_risk_money > 0
    entries = sorted(t.entry_time for t in trades)
    assert all((b - a).total_seconds() >= 120 for a, b in zip(entries, entries[1:]))   # min spacing rule


def test_verdict_logic():
    cfg = ResearchConfig(min_test_trades=30)
    good = r_summary([0.4, -1.0, 1.5, 0.2, 1.5, 0.3] * 10)
    zero = r_summary([])
    assert verdict(r_summary([1.0] * 5), good, zero, cfg)[0] == "insufficient_data"
    assert verdict(r_summary([-0.2, 0.1] * 20), good, zero, cfg)[0] == "rejected"
    bl = r_summary([0.9] * 40)
    assert "random entry" in verdict(good, good, bl, cfg)[1][0]
    assert verdict(good, good, r_summary([-0.1] * 40), cfg)[0] in ("candidate", "inconclusive")
    noisy = r_summary([3.0, -1.0, -1.0, -1.0, 1.5] * 8)
    assert verdict(noisy, good, r_summary([-0.5] * 40), cfg)[0] == "inconclusive"


def test_evaluate_setups_reports_all_and_stores_in_memory_a(settings, spec, store):
    tk = ticks(60_000)
    cfg = ResearchConfig(setups=("legacy_momentum", "liquidity_sweep"), risk_rewards=(1.0, 2.0), min_test_trades=5)
    rep = evaluate_setups(settings, spec, tk, cfg, store=store, data_source=SYNTHETIC_SOURCE)
    assert [s.setup for s in rep.setups] == ["legacy_momentum", "liquidity_sweep"]
    assert all(s.verdict in ("insufficient_data", "rejected", "inconclusive", "candidate") for s in rep.setups)
    runs = store.list_runs(MemoryDomain.HISTORICAL)
    assert len(runs) == 2 and all(r["kind"] == "research" and r["data_source"] == "synthetic" for r in runs)
    assert store.count_trades(MemoryDomain.FORWARD) == 0 and store.count_trades(MemoryDomain.VIRTUAL) == 0
    md = to_markdown(rep)
    assert "NOT live or forward results" in md and "legacy_momentum" in md
    json.dumps(rep.to_dict())


def test_daily_limits_roll_over_without_a_closed_trade(settings, spec):
    """Regression: a day's overtrading block must lift on the next day even if no trade closes."""
    s = settings.model_copy(update={"risk": settings.risk.model_copy(update={"max_trades_per_day": 1})})
    tk = list(synthetic_ticks(100_000, step_seconds=3, seed=4, drift=0.0, regime_switch_every=6000))
    trades, _ = run_rules(s, spec, tk, RuleParams(setup="legacy_momentum"))
    days = {t.entry_time.date() for t in trades}
    assert len(days) >= 2 and len(trades) == len(days)


# -- stats and features -----------------------------------------------------------------------------------

def test_stats_helpers():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    lo, hi = bootstrap_ci([1.0, 2.0, 3.0, 4.0, 5.0] * 4)
    assert lo < 3.0 < hi
    s = r_summary([1.0, -1.0, -1.0, 2.0])
    assert s["expectancy_r"] == pytest.approx(0.25) and s["max_drawdown_r"] == pytest.approx(2.0)


def test_bracket_outcome_conservative():
    fut = [bar(0, 100, 100.1, 99.9, 100), bar(1, 100, 103.5, 98.0, 101)]   # both barriers in one bar
    assert bracket_outcome(fut, "BUY", 1.0, 1.5, 0.0) == pytest.approx(-1.0)
    win = [bar(0, 100, 100.1, 99.9, 100), bar(1, 100, 102.0, 99.8, 101.9)]
    assert bracket_outcome(win, "BUY", 1.0, 1.5, 0.1) == pytest.approx(1.5 - 0.1)


def test_feature_evaluation_never_reads_test_split(spec):
    tk = list(synthetic_ticks(150_000, step_seconds=2, seed=5, regime_switch_every=20000))
    rep = evaluate_features(tk, spec, FeatureEvalConfig())
    assert rep["rows"] > rep["train_rows"] + rep["validation_rows"] > 0
    assert set(rep["kept"]) <= {f["name"] for f in rep["features"] if f["informative"]}


# -- decision agent: expected value after costs --------------------------------------------------------------

def _state():
    f = dict.fromkeys(FEATURE_NAMES, 0.0)
    f.update(mom_m5_3=1.0, mom_m1_5=1.0, tick_velocity=1.0, atr_m5=1.0)
    return MarketState(f, "trending_up", True, Tick(T0, 2400.0, 2400.2))


def _agent():
    m = ModelState()
    m.buy.b, m.buy.n_updates = 5.0, 100
    m.calibrator.hits[9], m.calibrator.total[9] = 60, 80      # calibrated hit rate ~0.74
    return TradingDecisionAgent(StrategyParams(), m)


def test_expected_value_is_after_costs():
    risk_money = lambda e, sl, lots: abs(e - sl) * 100 * lots   # noqa: E731
    cheap = _agent().decide(_state(), 10_000, lambda e, s: 0.1, lambda lots: 0.0, False, risk_money=risk_money)
    dear = _agent().decide(_state(), 10_000, lambda e, s: 0.1, lambda lots: 5.0, False, risk_money=risk_money)
    assert cheap.side == Side.BUY and dear.side == Side.BUY
    assert dear.proposal.ev_after_cost_r < cheap.proposal.ev_after_cost_r
    c = 5.0 / (abs(dear.proposal.entry - dear.proposal.stop_loss) * 100 * 0.1)
    p = dear.confidence
    assert dear.proposal.ev_after_cost_r == pytest.approx(p * (1.5 - c) - (1 - p) * (1 + c))
    huge = _agent().decide(_state(), 10_000, lambda e, s: 0.1, lambda lots: 200.0, False, risk_money=risk_money)
    assert huge.side == Side.WAIT and "after costs" in huge.explanation and "NO TRADE" in huge.explanation


def test_cli_research_writes_report(tmp_path, spec):
    from dataclasses import asdict

    from gold_ai.cli import main
    from gold_ai.memory.store import MemoryStore
    db = f"sqlite:///{tmp_path}/c.db"
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"database_url": db, "data_dir": str(tmp_path), "secret_key": "test-secret-key-0123456789"}))
    st = MemoryStore(db)
    st.kv_set(f"spec:{spec.broker}:{spec.symbol}", asdict(spec))
    st.save_ticks(spec.broker, spec.symbol, ticks(30_000), source=SYNTHETIC_SOURCE)
    assert main(["--config", str(cfg), "research", "--broker", spec.broker, "--symbol", spec.symbol,
                 "--setups", "legacy_momentum", "--rr", "1.5", "--min-test-trades", "5",
                 "--variants", "cost-round2"]) == 0
    reports = list((tmp_path / "research").glob("research-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text()
    assert "Data: synthetic" in text and "Feature evaluation" in text
    data = json.loads(next((tmp_path / "research").glob("research-*.json")).read_text())
    assert len(data["report"]["setups"][0]["variants"]) == 4


def test_streamed_research_matches_in_memory(settings, spec, store):
    from gold_ai.engines.loop import data_hash
    from gold_ai.research.stream import TickStream
    tk = ticks(30_000)
    store.save_ticks(spec.broker, spec.symbol, tk, source=SYNTHETIC_SOURCE)
    stream = TickStream.from_store(store, spec.broker, spec.symbol)
    assert stream.start == tk[0].time and stream.end == tk[-1].time
    cfg = ResearchConfig(setups=("legacy_momentum",), risk_rewards=(1.5,), min_test_trades=5)
    a = evaluate_setups(settings, spec, tk, cfg)
    b = evaluate_setups(settings, spec, stream, cfg)
    assert (a.ticks, a.m1_bars, a.data_hash) == (b.ticks, b.m1_bars, b.data_hash) == (len(tk), a.m1_bars, data_hash(tk))
    assert a.setups[0].test == b.setups[0].test and a.setups[0].baseline_test == b.setups[0].baseline_test
    assert evaluate_features(tk, spec)["rows"] == evaluate_features(stream, spec)["rows"]


def test_stream_rejects_out_of_order_ticks():
    from gold_ai.research.stream import TickStream
    tk = ticks(100)
    with pytest.raises(ValueError):
        list(TickStream(lambda: [tk[1], tk[0]], tk[0].time, tk[1].time))


def test_variant_grid_cost_gate_and_m5_trigger(settings, spec):
    tk = ticks(60_000)
    cfg = ResearchConfig(setups=("legacy_momentum",), risk_rewards=(1.5,), min_test_trades=5,
                         variants=({}, {"min_atr_spread": 1e6}, {"trigger_tf": "M5"}))
    rep = evaluate_setups(settings, spec, tk, cfg)
    keys = set(rep.setups[0].variants)
    assert keys == {"rr=1.5", "rr=1.5,min_atr_spread=1000000.0", "rr=1.5,trigger_tf=M5"}
    assert rep.setups[0].selected_key in keys
    gated, agent = run_rules(settings, spec, tk, RuleParams(setup="legacy_momentum", min_atr_spread=1e6))
    assert gated == [] and any("volatility too low" in k for k in agent.rejected)
    m5, _ = run_rules(settings, spec, tk, RuleParams(setup="legacy_momentum", trigger_tf="M5"))
    assert m5 and all(t.entry_time.minute % 5 == 0 for t in m5)        # decided only on M5 closes
    assert RuleParams(setup="breakout").version() == RuleParams(setup="breakout", trigger_tf="M1").version()


def test_intraday_scale_reads_every_timeframe_a_step_slower(settings, spec):
    from gold_ai.research.setup_eval import VARIANT_PRESETS
    from gold_ai.strategies.setups import scaled_tf

    assert [scaled_tf(t, "intraday") for t in ("M1", "M5", "M15")] == ["M5", "M15", "H1"]
    tk = ticks(200_000, seed=5)
    p = RuleParams(setup="random_baseline", setup_params={"probability": 0.3}, tf_scale="intraday",
                   max_hold_seconds=4 * 3600)
    assert RuleAgent(p).decide_on_bar_close == "M5"
    trades, _ = run_rules(settings, spec, tk, p)
    assert trades and all(t.entry_time.minute % 5 == 0 for t in trades)    # decided only on M5 closes
    scalp, _ = run_rules(settings, spec, tk, RuleParams(setup="random_baseline", setup_params={"probability": 0.3}))
    med = lambda ts: sorted(t.initial_risk_money / t.lots for t in ts)[len(ts) // 2]  # noqa: E731
    assert med(trades) > 1.5 * med(scalp)                    # stops on M15 ATR are wider than on M5 ATR
    assert RuleParams(setup="breakout").version() == RuleParams(setup="breakout", tf_scale="scalp").version()
    assert RuleParams(setup="breakout").version() != RuleParams(setup="breakout", tf_scale="intraday").version()
    with pytest.raises(ValueError):
        RuleParams(setup="breakout", tf_scale="weekly")
    cfg = ResearchConfig(setups=("range_reversion",), risk_rewards=(1.5,), min_test_trades=5,
                         variants=VARIANT_PRESETS["intraday-round3"])
    rep = evaluate_setups(settings, spec, tk, cfg)
    assert {k.split(",", 1)[1] for k in rep.setups[0].variants} == {
        "max_hold_seconds=14400,tf_scale=intraday", "max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5"}


def test_account_loss_stops_do_not_truncate_a_measurement(settings, spec):
    """A setup that loses early must still be measured on validation and test (root cause of round 4's 0-trade
    splits): the research harness switches off account-level loss stops, the trading engines keep them."""
    from gold_ai.risk.engine import RiskEngine, measurement_risk

    settings.risk.max_drawdown_pct = 0.5            # would block after one loss at 0.5% risk per trade
    settings.risk.max_daily_loss_pct = 0.5
    tk = ticks(120_000, seed=9)
    p = RuleParams(setup="random_baseline", setup_params={"probability": 0.2})
    trades, _ = run_rules(settings, spec, tk, p)
    losses = [t for t in trades if t.net_pnl < 0]
    assert losses and any(t.entry_time > losses[0].exit_time + timedelta(days=1) for t in trades)
    m = measurement_risk(settings.risk)
    assert m.max_drawdown_pct > 100 and m.max_spread_points == settings.risk.max_spread_points
    assert RiskEngine.create(settings.risk, spec, 1e4).cfg.max_drawdown_pct == 0.5      # trading rules unchanged
