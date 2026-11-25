"""Demo mirror tests with a fake MT5 module only — no broker is contacted."""
from datetime import timedelta
from types import SimpleNamespace

from gold_ai.brokers.mock_feed import synthetic_spec
from gold_ai.brokers.mt5_connector import AccountSnapshot
from gold_ai.config import Settings
from gold_ai.demo_mirror import DemoMirror, summarize_demo_log
from gold_ai.domain import ExitReason, Side, SimTrade, Tick, TradeProposal, utcnow
from gold_ai.engines.simulator import OpenPosition
from gold_ai.memory.store import MemoryStore
from gold_ai.security.auth import AuthService

from test_execution import LOGIN, FakeTradeMT5, O


class Conn:
    def __init__(self, mt5, mode="demo"):
        self.mt5, self.mode = mt5, mode

    def account(self):
        return AccountSnapshot("equiti", "EquitiSecurities-Demo", LOGIN, "USD", self.mode, True, 1000.0, 1000.0, 400)


class FakeMT5WithHistory(FakeTradeMT5):
    def history_deals_get(self, position=None):
        return [O(profit=-3.5, commission=0.0, swap=0.0, fee=0.0, entry=1, price=2397.0, comment="sl")]


def setup(tmp_path, enabled=True, trade_mode=0):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/x.db", secret_key="test-secret-key-0123456789",
                        demo_execution_enabled=enabled)
    store = MemoryStore(settings.database_url)
    auth = AuthService(settings, store)
    spec = synthetic_spec()
    tick = Tick(utcnow(), 2400.00, 2400.20)
    mt5 = FakeMT5WithHistory(trade_mode=trade_mode, tick=tick)
    loop = SimpleNamespace(on_fill=None, on_close=None, sim=SimpleNamespace(positions=[]))
    engine = SimpleNamespace(spec=spec, style="scalp", key=f"virtual:{spec.broker}:{spec.symbol}", loop=loop,
                             demo_mirror=None)
    m = DemoMirror(engine, Conn(mt5, {0: "demo", 2: "real"}[trade_mode]), auth, store, settings, lots=0.01,
                   max_risk_per_trade_pct=1.5)
    m.risk.started_at = tick.time - timedelta(minutes=10)    # observation window over
    return m, mt5, store, engine, tick


def prop(tick, sl_d=3.0, expl="test"):
    e = tick.ask
    return TradeProposal(Side.BUY, e, e - sl_d, e + sl_d * 1.5, 0.08, 0.7, tick.time + timedelta(seconds=60),
                         strategy_version="strat-abc", model_version="m1", explanation=expl)


def vtrade(p, tick, tid="v1"):
    return SimTrade(trade_id=tid, broker="equiti", account="virtual", symbol="XAUUSD", side=p.side, lots=0.08,
                    entry_time=tick.time, entry_price=p.entry, stop_loss=p.stop_loss, take_profit=p.take_profit,
                    strategy_version="strat-abc", model_version="m1")


def test_fill_is_mirrored_at_fixed_lot_and_closed_with_virtual(tmp_path):
    m, mt5, store, engine, tick = setup(tmp_path)
    p = prop(tick)
    t = vtrade(p, tick)
    engine.loop.on_fill(p, t, tick)
    assert len(mt5.sent) == 1 and mt5.sent[0]["volume"] == 0.01 and mt5.sent[0]["magic"] == m.magic
    assert m.status()["open_tickets"] == [mt5.positions[0].ticket]
    # virtual stop tightens -> broker stop follows
    engine.loop.sim.positions = [OpenPosition(t, None, None, None, current_sl=p.stop_loss + 1.0)]
    m._last_sync = 0
    m.sync()
    assert mt5.positions[0].sl == round(p.stop_loss + 1.0, 2)
    # virtual trade closes on time limit -> demo position closed at market, result logged from broker deals
    t.exit_reason = ExitReason.EXPIRY
    engine.loop.on_close(t)
    assert mt5.positions == [] and m.status()["open_tickets"] == []
    s = summarize_demo_log(store.kv_get("demo_execution_log"))
    assert s == {"closed": 1, "wins": 0, "net": -3.5, "opened": 1}


def test_exploration_disabled_and_real_accounts_never_sent(tmp_path):
    m, mt5, _, engine, tick = setup(tmp_path)
    engine.loop.on_fill(prop(tick, expl="[EXPLORATION] x"), vtrade(prop(tick), tick), tick)
    old = Tick(tick.time - timedelta(hours=1), 2400.0, 2400.2)
    engine.loop.on_fill(prop(old), vtrade(prop(old), old), old)        # warm-up replay
    assert mt5.sent == []
    m2, mt52, _, e2, t2 = setup(tmp_path / "b", enabled=False)
    e2.loop.on_fill(prop(t2), vtrade(prop(t2), t2), t2)
    assert mt52.sent == [] and m2.last_result["stage"] == "authorization"
    m3, mt53, _, e3, t3 = setup(tmp_path / "c", trade_mode=2)
    e3.loop.on_fill(prop(t3), vtrade(prop(t3), t3), t3)
    assert mt53.sent == [] and m3.last_result["stage"] == "authorization"


def test_stop_too_wide_for_fixed_lot_is_refused(tmp_path):
    m, mt5, _, engine, tick = setup(tmp_path)
    # 0.01 lot of a 100-oz contract: a 20-dollar stop risks 20 USD = 2% of 1000 > 1.5%
    engine.loop.on_fill(prop(tick, sl_d=20.0), vtrade(prop(tick, sl_d=20.0), tick), tick)
    assert mt5.sent == [] and m.last_result["stage"] == "risk"


def test_broker_side_close_is_noticed(tmp_path):
    m, mt5, store, engine, tick = setup(tmp_path)
    p = prop(tick)
    engine.loop.on_fill(p, vtrade(p, tick), tick)
    mt5.positions = []            # hit SL at the broker
    m._last_sync = 0
    m.sync()
    assert m.status()["open_tickets"] == []
    assert summarize_demo_log(store.kv_get("demo_execution_log"))["closed"] == 1
    assert m.risk.state.consecutive_losses == 1


def test_cost_filter_rejects_stops_too_tight_for_the_spread():
    from gold_ai.config import RiskConfig
    from gold_ai.risk.engine import RiskEngine
    spec = synthetic_spec()
    r = RiskEngine.create(RiskConfig(), spec, 10_000.0)
    tick = Tick(utcnow(), 2400.00, 2400.20)
    p = prop(tick, sl_d=3.0)
    p.lots = 0.05
    risk_money = 3.0 * spec.money_per_price_unit(0.05)
    assert r.evaluate(p, tick, 10_000.0, 0, est_cost=risk_money * 0.05).approved
    v = r.evaluate(p, tick, 10_000.0, 0, est_cost=risk_money * 0.30)
    assert not v.approved and any("stop too tight" in x for x in v.reasons)
