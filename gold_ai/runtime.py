"""Wires all agents and services into the API process.

Without --mt5 the API runs in research mode (stored ticks, backtests, walk-forward,
dashboard). With --mt5 it also connects to the local terminal read-only, captures
the broker's gold symbol spec, starts the tick collector and the live virtual engine,
and turns risk-approved non-exploratory virtual decisions into signal-only alerts.
No execution adapter is started here: real/demo execution stays off.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from fastapi import HTTPException

from .agents.decision import STYLES, StrategyParams, style_params
from .agents.health import HeartbeatRegistry, Supervisor, SystemHealthAgent
from .agents.institutional import InstitutionalFlowAgent
from .agents.maturity import assess, assess_all_brokers
from .agents.self_healing import SelfHealingAgent, model_scope
from .api.app import AppState, create_app, json_safe_any
from .backup import BackupService
from .brokers.mock_feed import synthetic_spec
from .config import Settings
from .domain import SymbolSpec
from .memory.store import MemoryStore
from .news import CalendarFileSource, NewsAgent
from .notifications import DashboardChannel, SignalService, channels_from_settings
from .notifications.service import TOKENS_KEY

log = logging.getLogger(__name__)


def register_services(state: AppState, *, news: NewsAgent | None = None,
                      institutional: InstitutionalFlowAgent | None = None,
                      heartbeats: HeartbeatRegistry | None = None,
                      health_agent: SystemHealthAgent | None = None,
                      supervisor: Supervisor | None = None) -> dict:
    """Attach optional service providers to the API. Returns the created service objects."""
    s = state
    news = news or NewsAgent(sources=[
        CalendarFileSource(os.path.expandvars(p), name=f"calendar_file:{Path(p).name}")
        for p in s.settings.news_calendar_files])
    institutional = institutional or InstitutionalFlowAgent()
    heartbeats = heartbeats or HeartbeatRegistry()
    dashboard = DashboardChannel()
    signals = SignalService(s.store, s.auth, channels_from_settings(s.settings, dashboard=dashboard))
    spec = next(iter(s.specs.values()), None) or synthetic_spec()
    healer = SelfHealingAgent(s.settings, spec, s.store)
    backups = BackupService(s.store, s.settings.database_url, Path(s.settings.data_dir) / "backups")
    health = health_agent or SystemHealthAgent(
        connector=next(iter(s.connectors.values()), None), store=s.store, heartbeats=heartbeats,
        supervisor=supervisor, disk_path=s.settings.data_dir if Path(s.settings.data_dir).exists() else ".")

    def maturity(broker: str | None = None):
        ops = health.run().as_operational_checks()
        if broker:
            return assess(s.store, broker, operational_checks=ops).to_dict()
        reports = assess_all_brokers(s.store, operational_checks=ops)
        return {"brokers": {b: r.to_dict() for b, r in reports.items()}}

    def signal_list():
        signals.expire_stale()
        toks = s.store.kv_get(TOKENS_KEY, {}) or {}
        out = []
        for sig in signals.list():
            d = sig.to_dict()
            if d.get("status") == "pending" and sig.id in toks:
                d["action_token"] = toks[sig.id]
            out.append(d)
        return out

    def signal_action(signal_id, action, token, user):
        r = signals.act(signal_id, action, token, actor=user.username)
        if not r.ok:
            raise HTTPException(400, r.reason)
        return {"ok": True, "reason": r.reason, "signal": r.signal.to_dict() if r.signal else None,
                "execution_requested": r.execution_requested, "order_placed": False}

    def news_view():
        now = datetime.now(timezone.utc)
        return json_safe_any({
            "events": [asdict(e) for e in news.events],
            "blackout_active": _blackout(state, now),
            "flags": news.regime_flags(now), "source_errors": getattr(news, "source_errors", []),
        })

    def institutional_view():
        f = institutional.features(datetime.now(timezone.utc))
        d = {"available": f.available, "features": f.values, "sources": f.sources}
        if not f.available:
            d["reason"] = "no licensed institutional data source configured"
        return d

    def system_health():
        d = health.run().to_dict()
        # Dashboard contract: `overall` plus a human-readable `detail`; raw values kept under `data`.
        checks = [{"name": c["name"], "status": c["status"], "detail": c.get("message", ""),
                   "data": c.get("detail")} for c in d.get("checks", [])]
        return json_safe_any({"overall": d.get("status"), "time": d.get("time"), "checks": checks})

    def owner_only(user):
        if user.role != "owner":
            raise HTTPException(403, "owner only")

    def apply_to_engine(version: str) -> dict:
        """Load an approved version's strategy into the live virtual engine it was validated for."""
        m = s.store.get_model(version) or {}
        broker, symbol, style = model_scope(m)
        engine = next((e for e in s.virtual_engines.values() if e.style == style
                       and (symbol is None or e.spec.symbol == symbol)
                       and (broker is None or e.spec.broker == broker)), None)
        if engine is None:
            return {"applied": False, "reason": f"no running {style} engine for {symbol or 'this model'}"}
        engine.apply_params(StrategyParams(**m["params"]), version)
        return {"applied": True, "engine": engine.key, "strategy_version": engine.agent.params.version()}

    def promote(version, user):
        owner_only(user)
        try:
            out = healer.promote(version, user)
            return json_safe_any({**out, "live_engine": apply_to_engine(version)})
        except (KeyError, ValueError, PermissionError, TypeError) as e:
            raise HTTPException(400, str(e))

    def rollback(version, user):
        owner_only(user)
        try:
            out = healer.rollback(version, user)
            return json_safe_any({**out, "live_engine": apply_to_engine(version)})
        except (KeyError, ValueError, PermissionError, TypeError) as e:
            raise HTTPException(400, str(e))

    def backup_list():
        root = backups.backup_dir
        if not root.exists():
            return []
        out = []
        for f in sorted(root.glob("gold_ai-*")):
            if f.suffix not in (".db", ".pgdump"):
                continue
            out.append({"name": f.name, "path": str(f), "size_bytes": f.stat().st_size,
                        "created_at": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()})
        return out

    def create_backup(user):
        owner_only(user)
        m = backups.backup(user)
        return {"name": m["file"], "path": m["path"], "size_bytes": m.get("size"), "created_at": m["created_at"],
                "sha256": m.get("sha256"), "status": m.get("status", "completed")}

    s.extras.update({
        "maturity": maturity,
        "self_healing": lambda: json_safe_any({"history": healer.history(),
                                               "current_diagnosis": (healer.history() or [None])[-1]}),
        "system_health": system_health,
        "news": news_view,
        "institutional": institutional_view,
        "signals": signal_list,
        "signal_action": signal_action,
        "promote": promote,
        "rollback": rollback,
        "backups": backup_list,
        "create_backup": create_backup,
    })
    return {"news": news, "institutional": institutional, "signals": signals, "healer": healer,
            "backups": backups, "health": health, "heartbeats": heartbeats, "dashboard_channel": dashboard}


SELF_HEAL_INTERVAL = timedelta(hours=24)
SELF_HEAL_RECENT_TRADES = 50


def scheduled_self_healing(engine, healer: SelfHealingAgent, store: MemoryStore, *,
                           error_counters: dict[str, int] | None = None, now: datetime | None = None,
                           interval: timedelta = SELF_HEAL_INTERVAL) -> dict | None:
    """One scheduled self-healing check on Memory C (live virtual) trades for the engine's broker/symbol.

    Runs at most once per `interval` (last run persisted, so restarts do not repeat it). The last
    SELF_HEAL_RECENT_TRADES closed virtual trades are compared with the ones before them; candidates are
    backtested/walk-forwarded on the last 2 days of stored ticks and only registered as "validated" —
    activation always needs the owner. Returns the recorded history entry, or None when not due.
    """
    from .domain import MemoryDomain
    from .engines.walkforward import WalkForwardConfig
    now = now or datetime.now(timezone.utc)
    style = getattr(engine, "style", "scalp")
    key = f"self_healing:last_cycle:{engine.spec.broker}:{engine.spec.symbol}" + ("" if style == "scalp" else f":{style}")
    last = store.kv_get(key)
    if last and now - datetime.fromisoformat(last) < interval:
        return None
    trades = [t for t in store.load_trades(MemoryDomain.VIRTUAL, broker=engine.spec.broker,
                                           symbols=[engine.spec.symbol])
              if t.exit_time is not None and t.context.get("style", "scalp") == style]
    trades.sort(key=lambda t: t.exit_time)
    recent, baseline = trades[-SELF_HEAL_RECENT_TRADES:], trades[:-SELF_HEAL_RECENT_TRADES][-200:]
    ticks = store.load_ticks(engine.spec.broker, engine.spec.symbol, now - timedelta(days=2), now)
    feed = [t for t in ticks if t.time >= now - timedelta(minutes=10)]
    healer.run_cycle(engine.agent.params, ticks, baseline, recent,
                     WalkForwardConfig(timedelta(hours=24), timedelta(hours=6), timedelta(hours=6)),
                     incumbent_version=engine.agent.model.version(), model=engine.agent.model,
                     error_counters=error_counters, now=now, data_source="mt5_live_demo",
                     actor="self_healing_scheduler", feed_ticks=feed)
    store.kv_set(key, now.isoformat())
    return healer.history()[-1]


def _blackout(state: AppState, now: datetime) -> bool:
    return any(e.loop.risk.blocked_by_news(now) is not None for e in state.virtual_engines.values())


def resolve_symbols(conn, broker: str, wanted: list[str], override: str | None = None) -> list[SymbolSpec]:
    """Match each wanted canonical instrument to the broker's own symbol and read its spec (read-only).

    `override` is a broker symbol name given on the command line (e.g. XAUUSD.sd); it replaces discovery
    for its instrument. Other instruments prefer the gold symbol's account-type suffix. An instrument the
    broker does not offer, or whose spec cannot be read, is logged and skipped.
    """
    from .instruments import INSTRUMENTS, canonical, suffix_of
    wanted = [w.upper() for w in wanted]
    over_inst = canonical(override) if override else None
    if override and over_inst is None:
        over_inst = "XAUUSD"   # unknown name: treat as the gold symbol, as before
    if over_inst and over_inst not in wanted:
        wanted.insert(0, over_inst)
    if "XAUUSD" in wanted:     # gold first: it is the primary instrument and sets the preferred suffix
        wanted.remove("XAUUSD")
        wanted.insert(0, "XAUUSD")
    specs: list[SymbolSpec] = []
    prefer: str | None = None
    for inst in wanted:
        if inst not in INSTRUMENTS:
            log.warning("unknown instrument %s in settings.symbols; supported: %s", inst, ", ".join(INSTRUMENTS))
            continue
        if inst == over_inst:
            names = [override]
        elif inst == "XAUUSD":
            names = conn.discover_gold()
        else:
            names = conn.discover(inst, prefer)
        if not names:
            log.warning("%s: no matching symbol at %s; skipped", inst, broker)
            continue
        try:
            spec = conn.symbol_spec(names[0], broker)
        except Exception as e:
            log.warning("%s: could not read spec for %s (%s); skipped", inst, names[0], e)
            continue
        if inst == "XAUUSD":
            prefer = suffix_of(spec.symbol)
        log.info("%s -> %s (%s)", inst, spec.symbol, broker)
        specs.append(spec)
    return specs


def _engine_worker(engine, heartbeats: HeartbeatRegistry, beat_name: str):
    warmed = threading.Event()

    def run_engine(stop: threading.Event) -> None:
        # Warm-up replays up to 7 days of stored ticks (minutes on a VPS), so it runs here rather
        # than before the API starts; it happens once, not again after a worker restart.
        if not warmed.is_set():
            engine.warm_up()
            warmed.set()
        while True:
            engine.poll_once()
            heartbeats.beat(beat_name)
            if stop.wait(engine.poll_interval) or engine._stop.is_set():
                return
    return run_engine


def build_runtime(settings: Settings, store: MemoryStore, *, use_mt5: bool = False, terminal_path: str | None = None,
                  symbol: str | None = None, dashboard_dir: str | None = None,
                  connector_factory: Callable | None = None):
    """Returns (app, supervisor). Call `supervisor.start()` to run the background workers; a crashed
    worker is restarted with exponential backoff and recorded as an incident."""
    state = AppState(settings, store)
    heartbeats = HeartbeatRegistry()
    supervisor = Supervisor(store, heartbeats=heartbeats)
    engines: list = []
    collectors: dict[str, object] = {}
    if use_mt5:
        from .brokers.mt5_connector import MT5ReadOnlyConnector
        from .collector import TickCollector
        from .engines.live_virtual import LiveVirtualEngine
        conn = connector_factory() if connector_factory else MT5ReadOnlyConnector(terminal_path=terminal_path)
        if not conn.connect():
            raise RuntimeError("could not connect to the MT5 terminal")
        acct = conn.account()
        specs = resolve_symbols(conn, acct.broker, settings.symbols, override=symbol)
        if not specs:
            raise RuntimeError("no symbol validated from broker metadata; pass --symbol explicitly")
        state.connectors[acct.broker] = conn
        for i, spec in enumerate(specs):
            store.kv_set(f"spec:{spec.broker}:{spec.symbol}",
                         {**asdict(spec), "filling_modes": list(spec.filling_modes)})
            store.audit("runtime", "mt5_connected", {"broker": acct.broker, "server": acct.server,
                                                     "account": acct.login, "mode": acct.trade_mode,
                                                     "symbol": spec.symbol})
            state.specs[(spec.broker, spec.symbol)] = spec
            # The first symbol keeps the original worker names; the others are suffixed with their symbol.
            tag = "" if i == 0 else f":{spec.symbol}"
            collector = TickCollector(conn, store, spec.broker, spec.symbol)
            collectors[spec.symbol] = collector
            supervisor.register(f"collector{tag}", collector.run)
            # One engine per trade style: scalping (M1/M5/M15, held up to 1 h) and swing (M15/H1/H4, up to
            # 3 days). Each has its own virtual account, open position, learning model and trade history.
            for style in settings.trade_styles:
                if style not in STYLES:
                    log.warning("unknown trade style %s in settings.trade_styles; supported: %s", style,
                                ", ".join(STYLES))
                    continue
                engine = LiveVirtualEngine(settings, spec, conn, store,
                                           params=style_params(style, exploration_rate=0.2),
                                           account=f"virtual-{acct.login}")
                sfx = "" if style == "scalp" else f":{style}"
                state.virtual_engines[f"{spec.broker}:{spec.symbol}{sfx}"] = engine
                engines.append(engine)
                name = f"live_virtual{sfx}{tag}"
                supervisor.register(name, _engine_worker(engine, heartbeats, name))

    svc = register_services(state, heartbeats=heartbeats, supervisor=supervisor)
    if engines:
        news: NewsAgent = svc["news"]
        signals: SignalService = svc["signals"]
        healers = {e.key: (svc["healer"] if i == 0 else SelfHealingAgent(settings, e.spec, store))
                   for i, e in enumerate(engines)}
        for engine in engines:
            engine.signal_hook = (lambda p, tick, e=engine:
                                  signals.create(p, tick, e.spec.broker, e.spec.symbol,
                                                 max_hold_seconds=e.agent.params.max_hold_seconds))

        def news_sync(stop: threading.Event) -> None:
            while True:   # refresh at start, then every 5 minutes
                now = datetime.now(timezone.utc)
                try:
                    n = news.refresh(now - timedelta(days=1), now + timedelta(days=7))
                    for e in engines:
                        news.sync_risk_engine(e.loop.risk)
                    log.info("news refresh: %d events loaded, %d upcoming high-impact in 24 h", n,
                             sum(e.impact == "high" for e in news.upcoming(now)))
                except Exception:
                    log.exception("news refresh failed")
                if stop.wait(300):
                    return
        supervisor.register("news_sync", news_sync)

        def self_healing(stop: threading.Event) -> None:
            # First check an hour after start (feed settled), then every 10 min whether the 24 h interval is due.
            delay = 3600
            while not stop.wait(delay):
                for e in engines:
                    try:
                        scheduled_self_healing(e, healers[e.key], store,
                                               error_counters={"collector": collectors[e.spec.symbol].errors})
                    except Exception:
                        log.exception("self-healing check failed for %s", e.key)
                delay = 600
        supervisor.register("self_healing", self_healing)
    app = create_app(state, dashboard_dir)
    return app, supervisor
