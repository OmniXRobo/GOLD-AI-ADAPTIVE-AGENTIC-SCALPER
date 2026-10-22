import threading
import time
from datetime import timedelta

from gold_ai.agents.health import (HeartbeatRegistry, HealthThresholds, Status, Supervisor, SystemHealthAgent,
                                   worst)
from gold_ai.brokers.mock_feed import FakeMT5
from gold_ai.brokers.mt5_connector import MT5ReadOnlyConnector
from gold_ai.domain import utcnow


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_worst():
    assert worst([Status.OK, Status.WARN]) == Status.WARN
    assert worst([Status.OK, Status.CRITICAL, Status.WARN]) == Status.CRITICAL
    assert worst([]) == Status.OK


def test_all_checks_ok(store, tmp_path):
    now = utcnow()
    hb = HeartbeatRegistry()
    hb.beat("decision", now - timedelta(seconds=1))
    conn = MT5ReadOnlyConnector(FakeMT5([{"name": "XAUUSD"}]))
    agent = SystemHealthAgent(connector=conn, store=store, feeds={"exness": lambda: now - timedelta(seconds=2)},
                              heartbeats=hb, expected_agents=["decision"], disk_path=str(tmp_path),
                              thresholds=HealthThresholds(cpu_load_critical=1e9, memory_critical_pct=101,
                                                          disk_critical_pct=101))
    rep = agent.run(now)
    by = {c.name: c for c in rep.checks}
    assert by["mt5"].status == Status.OK and by["database"].status == Status.OK
    assert by["feed:exness"].status == Status.OK and by["agent:decision"].status == Status.OK
    assert {"cpu", "memory", "disk"} <= set(by)
    assert rep.status != Status.CRITICAL
    d = rep.to_dict()
    assert d["status"] in ("ok", "warn") and all(isinstance(c["status"], str) for c in d["checks"])
    assert all(rep.as_operational_checks().values())


def test_failures_are_critical(store):
    now = utcnow()

    class DeadMT5(FakeMT5):
        def terminal_info(self):
            return None

    class BrokenStore:
        class engine:
            @staticmethod
            def connect():
                raise RuntimeError("db down")

    hb = HeartbeatRegistry()
    hb.beat("risk", now - timedelta(minutes=10))
    agent = SystemHealthAgent(connector=MT5ReadOnlyConnector(DeadMT5([])), store=BrokenStore(),
                              feeds={"stale": lambda: now - timedelta(minutes=5), "none": lambda: None},
                              heartbeats=hb, expected_agents=["market"])
    rep = agent.run(now)
    by = {c.name: c.status for c in rep.checks}
    assert by["mt5"] == by["database"] == by["feed:stale"] == by["feed:none"] == Status.CRITICAL
    assert by["agent:risk"] == by["agent:market"] == Status.CRITICAL
    assert rep.status == Status.CRITICAL
    assert rep.as_operational_checks()["database"] is False


def test_supervisor_restarts_crashing_worker_with_backoff(store):
    calls = {"n": 0}

    def flaky(stop: threading.Event):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError(f"boom {calls['n']}")
        stop.wait()

    sup = Supervisor(store, base_backoff=0.01, max_backoff=0.05, max_restarts=5, window_seconds=60)
    sup.register("collector", flaky)
    sup.start()
    assert wait_for(lambda: sup.status()["collector"]["state"] == "running" and calls["n"] == 3)
    st = sup.status()["collector"]
    assert st["restarts"] == 2 and "boom 2" in st["last_error"]
    agent = SystemHealthAgent(supervisor=sup)
    assert {c.name: c.status for c in agent.check_workers()}["worker:collector"] == Status.OK
    sup.stop()
    assert sup.status()["collector"]["state"] == "stopped"
    kinds = [i["kind"] for i in sup.incidents]
    assert kinds.count("crash") == 2 and kinds.count("restart") == 2
    assert len(store.kv_get("incidents")) == 4
    assert any(a["action"] == "worker_crash" for a in store.audit_log())


def test_supervisor_gives_up_after_max_restarts(store):
    def always(stop):
        raise ValueError("nope")

    sup = Supervisor(store, base_backoff=0.005, max_backoff=0.01, max_restarts=2, window_seconds=60)
    sup.register("bad", always)
    sup.start()
    assert wait_for(lambda: sup.status()["bad"]["state"] == "failed")
    assert sup.status()["bad"]["restarts"] == 2
    assert sup.incidents[-1]["kind"] == "gave_up"
    assert {c.name: c.status for c in SystemHealthAgent(supervisor=sup).check_workers()}["worker:bad"] \
        == Status.CRITICAL
    sup.stop()


def test_backoff_is_exponential_and_capped():
    sup = Supervisor(base_backoff=1, max_backoff=10)
    assert [sup.backoff(k) for k in (1, 2, 3, 4, 5, 6)] == [1, 2, 4, 8, 10, 10]
