"""Runs the persistence checks against a real PostgreSQL when GOLDAI_TEST_PG_URL is set."""
import os
import uuid
from datetime import datetime, timezone

import pytest

from gold_ai.domain import MemoryDomain, Side, SimTrade, Tick
from gold_ai.memory.store import MemoryStore

PG = os.environ.get("GOLDAI_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG, reason="GOLDAI_TEST_PG_URL not set")
T = datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_postgres_roundtrip():
    s = MemoryStore(PG)
    tid = uuid.uuid4().hex
    s.save_trade(MemoryDomain.VIRTUAL, SimTrade(tid, "pg", "a", "XAUUSD", Side.SELL, 0.1, T, 2400, 2401, 2398,
                                                "s", "m", exit_time=T, net_pnl=5.0, context={"regime": "r"}))
    got = [t for t in s.load_trades(MemoryDomain.VIRTUAL, broker="pg") if t.trade_id == tid][0]
    assert got.entry_time == T and got.side == Side.SELL and got.context == {"regime": "r"}
    s.save_ticks("pg", "XAUUSD", [Tick(T, 1.0, 1.2)], "synthetic")
    assert s.load_ticks("pg", "XAUUSD")[-1].ask == 1.2
    v = "pg-" + tid[:8]
    assert s.register_model(v, "s", {}, {"x": 1})
    assert not s.register_model(v, "s", {}, {"x": 2})
    s.kv_set("pgk", [1, 2])
    assert s.kv_get("pgk") == [1, 2]
