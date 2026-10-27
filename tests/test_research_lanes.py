"""Forward research lanes: research setups traded virtually on live quotes, simulation only, labelled, no signals."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from gold_ai.brokers.mock_feed import FakeMT5, synthetic_ticks
from gold_ai.brokers.mt5_connector import MT5ReadOnlyConnector
from gold_ai.domain import MemoryDomain, Tick
from gold_ai.engines.research_lanes import ResearchLaneEngine, lane_params
from gold_ai.runtime import build_runtime

from test_styles import BTC, GOLD


class ListSource:
    def __init__(self, ticks):
        self.ticks, self.i = list(ticks), 0

    def latest_tick(self, symbol):
        if self.i >= len(self.ticks):
            return None
        self.i += 1
        return self.ticks[self.i - 1]


def test_lane_trades_are_simulated_labelled_and_survive_restart(settings, spec, store):
    tk = list(synthetic_ticks(150_000, step_seconds=1, seed=5))
    src = ListSource(tk)
    cfg = {"setup": "random_baseline", "setup_params": {"probability": 0.3}, "tf_scale": "intraday",
           "max_hold_seconds": 4 * 3600}
    lane = ResearchLaneEngine(settings, spec, src, store, lane_params(cfg))
    assert lane.agent.decide_on_bar_close == "M5" and lane.signal_hook is None
    for _ in range(100_000):
        lane.poll_once()
    lane._persist()
    trades = store.load_trades(MemoryDomain.VIRTUAL)
    assert trades and store.count_trades(MemoryDomain.REAL) == 0
    for t in trades:
        assert t.context["style"] == "research" and t.context["exploration"] is True
        assert t.account == "research" and t.is_estimated_fill and t.strategy_version.startswith("rule-random_baseline")
    st = lane.status()
    assert st["setup"] == "random_baseline" and st["params"]["tf_scale"] == "intraday"
    open_before = len(lane.loop.sim.positions)
    again = ResearchLaneEngine(settings, spec, src, store, lane_params(cfg))       # restart
    assert len(again.loop.sim.positions) == open_before and again.loop.equity == lane.loop.equity
    with pytest.raises(TypeError):
        again.apply_params(None)


def test_lane_refuses_an_order_capable_source(settings, spec, store):
    class Trading:
        def latest_tick(self, symbol):
            return None

        def order_send(self, request):
            raise AssertionError("never called")

    with pytest.raises(TypeError):
        ResearchLaneEngine(settings, spec, Trading(), store, lane_params({"setup": "breakout"}))


def test_runtime_starts_lanes_for_gold_only(settings, store):
    now = datetime.now(timezone.utc)
    fake = FakeMT5([GOLD, BTC], {"XAUUSD.sd": Tick(now, 4100.0, 4100.2), "BTCUSD.sd": Tick(now, 108_000, 108_015)},
                   server="Equiti-Demo", company="Equiti")
    settings.symbols = ["XAUUSD", "BTCUSD"]
    app, sup = build_runtime(settings, store, use_mt5=True,
                             connector_factory=lambda: MT5ReadOnlyConnector(fake, server_utc_offset_hours=0))
    lanes = app.state.gold.research_lanes
    assert sorted(lane.agent.params.setup for lane in lanes.values()) == ["breakout", "failed_breakout",
                                                                        "trend_pullback"]
    assert all(lane.spec.symbol == "XAUUSD.sd" and lane.agent.params.tf_scale == "intraday" for lane in lanes.values())
    app.state.gold.auth.create_user("owner", "owner-pass-123", "owner")
    c = TestClient(app)
    tok = c.post("/api/auth/login", json={"username": "owner", "password": "owner-pass-123"}).json()["token"]
    ov = c.get("/api/overview", headers={"Authorization": f"Bearer {tok}"}).json()
    assert len(ov["research_lanes"]) == 3 and all(x["style"] == "research" for x in ov["research_lanes"])
    assert fake.order_send_calls == 0
