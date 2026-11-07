"""Trade-History Learner: replays past virtual trades out of sample and only proposes; the owner decides."""
import math
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from gold_ai.agents import trade_learner as tl
from gold_ai.agents.decision import StrategyParams, _LEARN_FEATURES
from gold_ai.domain import ExitReason, MemoryDomain, Side, SimTrade
from gold_ai.strategies import investigation

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def trades(n, seed=0, edge=True):
    """Trades paying +1.5R / -1R where `mom_m1_5` > 0 wins 75% of the time (edge) and <= 0 wins 20%; or a 50%
    win rate whatever the feature (profitable, but nothing for a filter to find)."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        f = dict.fromkeys(_LEARN_FEATURES, 0.0)
        f["mom_m1_5"] = rng.uniform(-3, 3)
        p = (0.75 if f["mom_m1_5"] > 0 else 0.2) if edge else 0.5
        win = rng.random() < p
        t0 = T0 + timedelta(hours=i)
        out.append(SimTrade(f"t{i}", "equiti", "virtual", "XAUUSD.pr", Side.BUY, 0.1, t0, 4000.0, 3995.0, 4007.5,
                            "strat-x", "model-x", exit_time=t0 + timedelta(minutes=30), exit_price=4001.0,
                            exit_reason=ExitReason.TAKE_PROFIT if win else ExitReason.STOP_LOSS,
                            net_pnl=15.0 if win else -10.0, initial_risk_money=10.0,
                            context={"features": f, "style": "scalp"}))
    return out


def test_replay_scores_each_trade_before_learning_it():
    ts = trades(80)
    rows = tl.replay(ts, StrategyParams(min_samples=10))
    # The first trades are scored by an untrained model: unknown (immature), never by one that saw them.
    assert all(math.isnan(conf) for _, conf, _ in rows[:10])
    # Changing a later trade's outcome cannot change the score given to an earlier one.
    flipped = trades(80)
    flipped[-1].net_pnl = -flipped[-1].net_pnl
    again = tl.replay(flipped, StrategyParams(min_samples=10))
    assert [r[1] for r in rows[:-1] if not math.isnan(r[1])] == [r[1] for r in again[:-1] if not math.isnan(r[1])]


def test_finds_a_real_edge_out_of_sample_and_rejects_noise():
    p = StrategyParams(min_samples=20, min_confidence=0.95)    # a current threshold too strict to approve anything
    crit = tl.LearnerCriteria(min_trades=60, min_holdout_selected=15)
    good = tl.evaluate(trades(400), p, broker="equiti", symbol="XAUUSD.pr", crit=crit)
    assert good.verdict == "candidate", good.reasons
    assert good.holdout_chosen["expectancy_r"] > good.holdout_all["expectancy_r"] + 0.05
    assert good.top_features["buy"][0][0] == "mom_m1_5"
    noise = tl.evaluate(trades(400, edge=False), p, broker="equiti", symbol="XAUUSD.pr", crit=crit)
    assert noise.verdict != "candidate"
    few = tl.evaluate(trades(20), p, broker="equiti", symbol="XAUUSD.pr", crit=crit)
    assert few.verdict == "insufficient_data" and "required" in few.reasons[0]


def test_candidate_is_registered_validated_never_activated(store, spec):
    for t in trades(400):
        store.save_trade(MemoryDomain.VIRTUAL, t)
    params = StrategyParams(min_samples=20, min_confidence=0.95)
    from gold_ai.agents.decision import ModelState
    engine = SimpleNamespace(spec=SimpleNamespace(broker="equiti", symbol="XAUUSD.pr"), style="scalp",
                             key="virtual:equiti:XAUUSD.pr",
                             agent=SimpleNamespace(params=params, model=ModelState()))
    learner = tl.TradeHistoryLearner(store, tl.LearnerCriteria(min_trades=60, min_holdout_selected=15))
    rep = learner.run(engine)
    assert engine.agent.params is params                     # nothing changed on the engine
    assert learner.latest()["equiti:XAUUSD.pr:scalp"]["report_id"] == rep.report_id
    m = store.get_model(rep.registered_version)
    assert m["stage"] == "validated" and m["params"]["min_confidence"] == rep.chosen_threshold
    # learned candidates belong to the adaptive family, so the open investigation blocks their promotion
    assert investigation.family_of(rep.registered_version) == investigation.ADAPTIVE_FAMILY


def test_context_signals_flag_only_fields_that_agree_across_the_history():
    ts = trades(300, edge=False)
    rng = random.Random(1)
    for t in ts:
        won = t.net_pnl > 0
        t.context["context"] = {"usd_strength_60m_bp": (5.0 if won else -5.0) + rng.gauss(0, 3),
                                "noise_field": rng.gauss(0, 1), "regime_hmm": "ranging"}
    sig = {d["field"]: d for d in tl.context_signals(ts, 0.3)}
    assert sig["usd_strength_60m_bp"]["informative"] and sig["usd_strength_60m_bp"]["rho_later"] > 0.3
    assert not sig["noise_field"]["informative"]
    assert "regime_hmm" not in sig                                     # text fields are not ranked


def test_context_agent_records_news_intermarket_and_technical_data():
    from gold_ai.brokers.mock_feed import synthetic_ticks
    from gold_ai.domain import Tick
    from gold_ai.market.features import MarketIntelligenceAgent
    from gold_ai.market.trade_context import IntermarketMonitor, TradeContextAgent
    from gold_ai.news.events import EconomicEvent

    ticks = list(synthetic_ticks(70_000, start=T0, step_seconds=1.0))
    market = MarketIntelligenceAgent()
    for t in ticks:
        market.on_tick(t)
    state = market.state(advance=True)
    now = ticks[-1].time
    im = IntermarketMonitor()
    for m in (61, 0):                       # EURUSD down 10 bp and USDJPY up 10 bp: the dollar is stronger
        ts = now - timedelta(minutes=m)
        im.observe("EURUSD.sd", Tick(ts, 1.1000 if m else 1.0989, 1.1001 if m else 1.0990))
        im.observe("USDJPY.sd", Tick(ts, 150.00 if m else 150.15, 150.01 if m else 150.16))
    news = SimpleNamespace(events=lambda: [
        EconomicEvent(now - timedelta(minutes=30), "CPI", "USD", "high", forecast=0.2, actual=0.4),
        EconomicEvent(now + timedelta(minutes=90), "FOMC", "USD", "high"),
        EconomicEvent(now + timedelta(minutes=5), "GDP", "EUR", "high")])
    ctx = TradeContextAgent(news=news, intermarket=im).snapshot("XAUUSD.pr", ticks[-1], state)
    assert ctx["news_minutes_to_next_high"] == 90.0 and ctx["news_minutes_since_last_high"] == 30.0
    assert ctx["news_last_high_surprise"] == 1.0
    assert ctx["usd_strength_60m_bp"] > 5 and ctx["usd_strength_pairs"] == 2
    assert "tech_spread_atr" in ctx and "regime_hmm" in ctx and "errors" not in ctx
    eur = TradeContextAgent(news=news).snapshot("EURUSD.sd", ticks[-1], state)
    assert eur["news_minutes_to_next_high"] == 5.0                      # EUR events count for EURUSD


def test_loop_stores_context_with_each_trade_without_changing_decisions(settings, spec):
    from gold_ai.brokers.mock_feed import synthetic_ticks
    from gold_ai.engines.loop import TradingLoop
    from gold_ai.strategies.agent import RuleAgent, RuleParams

    ticks = list(synthetic_ticks(30_000, start=T0, step_seconds=1.0))
    p = RuleParams(setup="random_baseline", setup_params={"probability": 0.3, "seed": 3})

    def run(provider):
        loop = TradingLoop(settings, spec, RuleAgent(p), broker="b", account="a", learn=False, simulation=True)
        loop.context_provider = provider
        return loop.run(ticks)

    plain = run(None)
    seen = []
    with_ctx = run(lambda tick, st: seen.append(tick.time) or {"usd_strength_60m_bp": 1.0})
    broken = run(lambda tick, st: 1 / 0)                             # a failing provider never blocks a trade
    assert plain and [t.entry_price for t in with_ctx] == [t.entry_price for t in plain]
    assert all(t.context["context"] == {"usd_strength_60m_bp": 1.0} for t in with_ctx)
    assert [t.entry_price for t in broken] == [t.entry_price for t in plain]
    assert all(t.context["context"] == {"errors": ["ZeroDivisionError"]} for t in broken)
