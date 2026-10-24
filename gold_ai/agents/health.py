"""System Health & Recovery Agent.

Checks: MT5 connector, database, data-feed freshness, agent heartbeats, supervised
worker threads and host resources (CPU load, memory, disk). Each check returns
ok / warn / critical; the overall status is the worst of them.

`Supervisor` runs registered worker callables in threads and restarts them after a
crash with exponential backoff, giving up after `max_restarts` within `window_seconds`.
Every crash / restart / give-up is recorded as an incident. Restarting a worker never
changes trading permissions: it only restarts observation / simulation code.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from ..domain import utcnow

log = logging.getLogger(__name__)

try:  # optional
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - environment dependent
    psutil = None


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"


_ORDER = {Status.OK: 0, Status.WARN: 1, Status.CRITICAL: 2}


def worst(statuses) -> Status:
    out = Status.OK
    for s in statuses:
        if _ORDER[s] > _ORDER[out]:
            out = s
    return out


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    detail: dict = field(default_factory=dict)


@dataclass
class HealthReport:
    status: Status
    checks: list[CheckResult]
    time: datetime

    def to_dict(self) -> dict:
        return {"status": self.status.value, "time": self.time.isoformat(),
                "checks": [dict(asdict(c), status=c.status.value) for c in self.checks]}

    def as_operational_checks(self) -> dict[str, bool]:
        """name -> passed mapping suitable for maturity.assess(operational_checks=...)."""
        return {c.name: c.status != Status.CRITICAL for c in self.checks}


@dataclass
class HealthThresholds:
    feed_warn_seconds: float = 10.0
    feed_critical_seconds: float = 60.0
    heartbeat_warn_seconds: float = 30.0
    heartbeat_critical_seconds: float = 120.0
    cpu_load_warn: float = 0.85          # 1-min load average per CPU
    cpu_load_critical: float = 1.5
    memory_warn_pct: float = 85.0
    memory_critical_pct: float = 95.0
    disk_warn_pct: float = 85.0
    disk_critical_pct: float = 95.0
    db_latency_warn_ms: float = 500.0
    mt5_latency_warn_ms: float = 1000.0


class HeartbeatRegistry:
    """Thread-safe name -> last heartbeat time."""

    def __init__(self):
        self._lock = threading.Lock()
        self._beats: dict[str, datetime] = {}

    def beat(self, name: str, now: datetime | None = None) -> None:
        with self._lock:
            self._beats[name] = now or utcnow()

    def last(self, name: str) -> datetime | None:
        with self._lock:
            return self._beats.get(name)

    def snapshot(self) -> dict[str, datetime]:
        with self._lock:
            return dict(self._beats)


# -- resource probes (stdlib first) ------------------------------------------------
def memory_usage_pct() -> float | None:
    if psutil is not None:  # pragma: no cover - optional
        return float(psutil.virtual_memory().percent)
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = float(v.split()[0])
        total, avail = info["MemTotal"], info.get("MemAvailable", info.get("MemFree", 0.0))
        return 100.0 * (1 - avail / total) if total else None
    except (OSError, KeyError, ValueError):
        return None


def cpu_load_per_cpu() -> float | None:
    try:
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except (OSError, AttributeError):  # Windows has no getloadavg
        if psutil is not None:  # pragma: no cover - optional
            return psutil.cpu_percent(interval=None) / 100.0
        return None


def disk_usage_pct(path: str) -> float | None:
    try:
        u = shutil.disk_usage(path)
        return 100.0 * u.used / u.total if u.total else None
    except OSError:
        return None


def _grade(value: float | None, warn: float, critical: float) -> Status:
    if value is None:
        return Status.WARN
    return Status.CRITICAL if value >= critical else Status.WARN if value >= warn else Status.OK


class SystemHealthAgent:
    """All dependencies are optional; a missing dependency is simply not checked.

    connector: object with .health() -> dict (MT5ReadOnlyConnector)
    store:     MemoryStore (DB connectivity via SELECT 1)
    feeds:     name -> callable returning the last tick time (datetime | None)
    """

    def __init__(self, *, connector: Any = None, store: Any = None,
                 feeds: dict[str, Callable[[], datetime | None]] | None = None,
                 heartbeats: HeartbeatRegistry | None = None, expected_agents: list[str] | None = None,
                 supervisor: "Supervisor | None" = None, disk_path: str = ".",
                 thresholds: HealthThresholds | None = None):
        self.connector, self.store = connector, store
        self.feeds = feeds or {}
        self.heartbeats = heartbeats
        self.expected_agents = expected_agents or []
        self.supervisor = supervisor
        self.disk_path = disk_path
        self.th = thresholds or HealthThresholds()

    def check_mt5(self) -> CheckResult:
        try:
            h = self.connector.health()
        except Exception as e:  # connector errors are a health finding, not a crash
            return CheckResult("mt5", Status.CRITICAL, f"health() raised: {e}")
        if not h.get("connected"):
            return CheckResult("mt5", Status.CRITICAL, "terminal not connected", h)
        lat = h.get("api_latency_ms")
        if lat is not None and lat > self.th.mt5_latency_warn_ms:
            return CheckResult("mt5", Status.WARN, f"slow terminal API ({lat:.0f} ms)", h)
        return CheckResult("mt5", Status.OK, "connected", h)

    def check_db(self) -> CheckResult:
        from sqlalchemy import text
        t0 = time.perf_counter()
        try:
            with self.store.engine.connect() as c:
                c.execute(text("SELECT 1")).scalar()
        except Exception as e:
            return CheckResult("database", Status.CRITICAL, f"query failed: {e}")
        ms = (time.perf_counter() - t0) * 1000
        st = Status.WARN if ms > self.th.db_latency_warn_ms else Status.OK
        return CheckResult("database", st, f"SELECT 1 in {ms:.1f} ms", {"latency_ms": round(ms, 3)})

    def check_feeds(self, now: datetime) -> list[CheckResult]:
        out = []
        for name, fn in self.feeds.items():
            try:
                last = fn()
            except Exception as e:
                out.append(CheckResult(f"feed:{name}", Status.CRITICAL, f"feed probe raised: {e}"))
                continue
            if last is None:
                out.append(CheckResult(f"feed:{name}", Status.CRITICAL, "no ticks received"))
                continue
            age = (now - last).total_seconds()
            st = _grade(age, self.th.feed_warn_seconds, self.th.feed_critical_seconds)
            out.append(CheckResult(f"feed:{name}", st, f"last tick {age:.1f}s ago",
                                   {"age_seconds": age, "last": last.isoformat()}))
        return out

    def check_heartbeats(self, now: datetime) -> list[CheckResult]:
        snap = self.heartbeats.snapshot() if self.heartbeats else {}
        if self.supervisor is not None:
            # The supervisor beats "worker:<name>" only when it (re)starts a worker, so its age says nothing
            # about a long-running worker; check_workers reports those threads' real state instead.
            snap = {k: v for k, v in snap.items() if not k.startswith("worker:")}
        out = []
        for name in sorted(set(snap) | set(self.expected_agents)):
            last = snap.get(name)
            if last is None:
                out.append(CheckResult(f"agent:{name}", Status.CRITICAL, "no heartbeat ever received"))
                continue
            age = (now - last).total_seconds()
            st = _grade(age, self.th.heartbeat_warn_seconds, self.th.heartbeat_critical_seconds)
            out.append(CheckResult(f"agent:{name}", st, f"last heartbeat {age:.1f}s ago", {"age_seconds": age}))
        return out

    def check_workers(self) -> list[CheckResult]:
        out = []
        for name, w in self.supervisor.status().items():
            st = {"running": Status.OK, "restarting": Status.WARN, "stopped": Status.OK,
                  "exited": Status.WARN, "failed": Status.CRITICAL}.get(w["state"], Status.WARN)
            out.append(CheckResult(f"worker:{name}", st, w["state"], w))
        return out

    def check_resources(self) -> list[CheckResult]:
        th = self.th
        cpu, mem, disk = cpu_load_per_cpu(), memory_usage_pct(), disk_usage_pct(self.disk_path)
        return [
            CheckResult("cpu", _grade(cpu, th.cpu_load_warn, th.cpu_load_critical),
                        "unavailable" if cpu is None else f"load/cpu {cpu:.2f}", {"load_per_cpu": cpu}),
            CheckResult("memory", _grade(mem, th.memory_warn_pct, th.memory_critical_pct),
                        "unavailable" if mem is None else f"{mem:.1f}% used", {"used_pct": mem}),
            CheckResult("disk", _grade(disk, th.disk_warn_pct, th.disk_critical_pct),
                        "unavailable" if disk is None else f"{disk:.1f}% used",
                        {"used_pct": disk, "path": os.path.abspath(self.disk_path)}),
        ]

    def run(self, now: datetime | None = None) -> HealthReport:
        now = now or utcnow()
        checks: list[CheckResult] = []
        if self.connector is not None:
            checks.append(self.check_mt5())
        if self.store is not None:
            checks.append(self.check_db())
        checks += self.check_feeds(now)
        checks += self.check_heartbeats(now)
        if self.supervisor is not None:
            checks += self.check_workers()
        checks += self.check_resources()
        return HealthReport(worst(c.status for c in checks), checks, now)


# -- supervisor ----------------------------------------------------------------------
@dataclass
class _Worker:
    name: str
    target: Callable[[threading.Event], None]
    restart: bool = True
    state: str = "registered"      # registered|running|restarting|stopped|exited|failed
    restarts: int = 0
    crash_times: list[float] = field(default_factory=list)
    last_error: str = ""
    thread: threading.Thread | None = None


class Supervisor:
    """Runs `target(stop_event)` callables in threads; restarts crashed workers with backoff.

    Workers should return promptly once `stop_event` is set.
    """

    def __init__(self, store: Any = None, *, base_backoff: float = 1.0, max_backoff: float = 60.0,
                 max_restarts: int = 5, window_seconds: float = 300.0,
                 heartbeats: HeartbeatRegistry | None = None, clock: Callable[[], float] = time.monotonic):
        self.store = store
        self.base_backoff, self.max_backoff = base_backoff, max_backoff
        self.max_restarts, self.window = max_restarts, window_seconds
        self.heartbeats = heartbeats
        self.clock = clock
        self._workers: dict[str, _Worker] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.incidents: list[dict] = []

    def register(self, name: str, target: Callable[[threading.Event], None], *, restart: bool = True) -> None:
        if name in self._workers:
            raise ValueError(f"worker {name} already registered")
        self._workers[name] = _Worker(name, target, restart)

    def backoff(self, consecutive_crashes: int) -> float:
        return min(self.max_backoff, self.base_backoff * 2 ** max(0, consecutive_crashes - 1))

    def _incident(self, name: str, kind: str, detail: dict) -> None:
        rec = {"time": utcnow().isoformat(), "worker": name, "kind": kind, **detail}
        with self._lock:
            self.incidents.append(rec)
        log.warning("supervisor incident: %s", rec)
        if self.store is not None:
            try:
                self.store.audit("supervisor", f"worker_{kind}", rec)
                hist = list(self.store.kv_get("incidents", []) or [])
                hist.append(rec)
                self.store.kv_set("incidents", hist[-1000:])
            except Exception:  # never let incident recording kill the supervisor
                log.exception("could not persist incident")

    def _run(self, w: _Worker) -> None:
        while not self._stop.is_set():
            w.state = "running"
            if self.heartbeats:
                self.heartbeats.beat(f"worker:{w.name}")
            try:
                w.target(self._stop)
            except Exception as e:
                now = self.clock()
                w.crash_times = [t for t in w.crash_times if now - t <= self.window] + [now]
                w.last_error = f"{type(e).__name__}: {e}"
                self._incident(w.name, "crash", {"error": w.last_error,
                                                 "traceback": traceback.format_exc(limit=5),
                                                 "crashes_in_window": len(w.crash_times)})
                if not w.restart or len(w.crash_times) > self.max_restarts:
                    w.state = "failed"
                    self._incident(w.name, "gave_up", {"restarts": w.restarts,
                                                       "reason": "restart disabled" if not w.restart else
                                                       f"> {self.max_restarts} crashes in {self.window}s"})
                    return
                delay = self.backoff(len(w.crash_times))
                w.state = "restarting"
                if self._stop.wait(delay):
                    break
                w.restarts += 1
                self._incident(w.name, "restart", {"attempt": w.restarts, "backoff_seconds": delay})
                continue
            if not self._stop.is_set():
                w.state = "exited"
                return
        w.state = "stopped"

    def start(self) -> None:
        self._stop.clear()
        for w in self._workers.values():
            if w.thread is None or not w.thread.is_alive():
                w.thread = threading.Thread(target=self._run, args=(w,), name=f"worker-{w.name}", daemon=True)
                w.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for w in self._workers.values():
            if w.thread is not None:
                w.thread.join(timeout)
                if not w.thread.is_alive() and w.state in ("running", "restarting"):
                    w.state = "stopped"

    def status(self) -> dict[str, dict]:
        return {n: {"state": w.state, "restarts": w.restarts, "last_error": w.last_error,
                    "alive": bool(w.thread and w.thread.is_alive())} for n, w in self._workers.items()}
