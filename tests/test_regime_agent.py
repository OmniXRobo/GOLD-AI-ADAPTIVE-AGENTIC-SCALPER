"""Regime agent (HMM + change-point) and its out-of-sample benchmark. Synthetic bars only (labelled as such)."""
import json
import random
from datetime import datetime, timedelta, timezone

from gold_ai.agents.regime import ChangePointDetector, GaussianHMM, RegimeAgent, RegimeConfig
from gold_ai.domain import Candle
from gold_ai.research.regime_eval import RegimeEvalConfig, evaluate_regimes, regime_markdown


def synthetic_bars(n=3000, seed=1, block=150):
    """Alternating calm and volatile blocks (synthetic test data, not market data)."""
    rng = random.Random(seed)
    t = datetime(2024, 1, 2, tzinfo=timezone.utc)
    price, bars, vol_of = 2000.0, [], []
    for i in range(n):
        vol = 0.3 if (i // block) % 2 == 0 else 2.0
        o = price
        c = max(1.0, o + rng.gauss(0, vol))
        hi = max(o, c) + abs(rng.gauss(0, vol / 2))
        lo = min(o, c) - abs(rng.gauss(0, vol / 2))
        bars.append(Candle(t, o, hi, lo, c, 10))
        vol_of.append(vol)
        price, t = c, t + timedelta(minutes=5)
    return bars, vol_of


def test_hmm_separates_volatility_states_causally():
    bars, vol_of = synthetic_bars()
    agent = RegimeAgent(RegimeConfig(n_states=2)).fit(bars[:1500])
    assert sorted(agent.labels) == ["ranging", "volatile"]
    right = total = 0
    for i, b in enumerate(bars[1500:], start=1500):
        r = agent.update(b)
        if r.state_label == "unknown" or i % 150 < 10:   # skip warm-up and the bars right after a switch
            continue
        total += 1
        right += (r.state_label == "volatile") == (vol_of[i] > 1)
    assert right / total > 0.9


def test_reading_is_causal():
    bars, _ = synthetic_bars(1200)
    a = RegimeAgent(RegimeConfig(n_states=2)).fit(bars[:800])
    first = [a.update(b) for b in bars[:900]]
    a.reset_filter()
    second = [a.update(b) for b in bars[:900] + bars[900:1000]]   # later bars cannot change earlier readings
    assert [r.probabilities for r in first] == [r.probabilities for r in second[:900]]


def test_change_point_detector_flags_a_jump():
    cpd = ChangePointDetector(hazard=1 / 100)
    rng = random.Random(3)
    probs = [cpd.update(rng.gauss(0, 1)) for _ in range(200)]
    assert max(probs[50:]) < 0.5
    after = [cpd.update(rng.gauss(8, 1)) for _ in range(5)]
    assert max(after) > 0.5


def test_uncertain_reading_gives_no_trade_reason():
    bars, _ = synthetic_bars(1200)
    a = RegimeAgent(RegimeConfig(n_states=2, min_confidence=1.01)).fit(bars[:800])
    r = [a.update(b) for b in bars[800:900]][-1]
    assert r.uncertain and r.label == "uncertain"
    assert a.wait_reason(r).startswith("NO TRADE: regime uncertain")


def test_round_trip_serialisation():
    bars, _ = synthetic_bars(1200)
    a = RegimeAgent(RegimeConfig(n_states=3)).fit(bars[:800])
    b = RegimeAgent.from_dict(json.loads(json.dumps(a.to_dict())))
    ra = [a.update(x) for x in bars[800:850]][-1]
    rb = [b.update(x) for x in bars[800:850]][-1]
    assert ra.probabilities == rb.probabilities


def test_hmm_needs_enough_data():
    try:
        GaussianHMM(4).fit([(0.0, 0.0, 0.0)] * 10)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_benchmark_on_switching_volatility():
    bars, _ = synthetic_bars(8000)
    rep = evaluate_regimes(bars, RegimeEvalConfig(horizon=6, min_test_samples=100), RegimeConfig(n_states=3))
    assert rep["samples"]["test"] >= 100
    hmm_r2 = rep["methods"]["hmm"]["test"]["vol_r2"]
    assert hmm_r2 > 0.3                                   # volatility blocks persist, so labels predict them
    assert rep["methods"]["random"]["test"]["vol_r2"] < 0.05
    assert rep["verdict"] in ("hmm_better_than_rule", "hmm_not_better_than_rule")
    md = regime_markdown(rep)
    assert "Future-vol R²" in md and "Research only" in md


def test_benchmark_insufficient_data():
    bars, _ = synthetic_bars(600)
    assert evaluate_regimes(bars)["verdict"] == "insufficient_data"


def test_cli_regime_eval_writes_report(tmp_path):
    from gold_ai.brokers.mock_feed import synthetic_ticks
    from gold_ai.cli import main
    from gold_ai.memory.store import MemoryStore
    db = f"sqlite:///{tmp_path}/r.db"
    cfg = tmp_path / "r.json"
    cfg.write_text(json.dumps({"database_url": db, "data_dir": str(tmp_path), "secret_key": "test-secret-key-0123456789"}))
    MemoryStore(db).save_ticks("exness", "XAUUSDm", list(synthetic_ticks(60_000, step_seconds=10.0)),
                               source="synthetic")
    assert main(["--config", str(cfg), "regime-eval", "--broker", "exness", "--symbol", "XAUUSDm",
                 "--tf", "M1", "--states", "3"]) == 0
    md = next((tmp_path / "research").glob("regime-*.md")).read_text()
    assert "Regime benchmark (M1" in md and "Verdict" in md
    data = json.loads(next((tmp_path / "research").glob("regime-*.json")).read_text())
    assert data["symbol"] == "XAUUSDm" and data["bars"] > 5000
