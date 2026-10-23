"""FastAPI backend: dashboard + mobile-ready REST/WebSocket API.

Every route except /api/health and /api/auth/login requires a bearer token, and
mutating routes check role permissions. Simulated and actual results are always
returned with an explicit `simulated` flag and label.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agents.decision import StrategyParams
from ..brokers.mock_feed import SYNTHETIC_SOURCE, synthetic_spec, synthetic_ticks
from ..config import Settings
from ..domain import MemoryDomain, SymbolSpec
from ..engines.backtest import run_backtest
from ..engines.metrics import compute_metrics, json_safe
from ..engines.walkforward import WalkForwardConfig, run_walkforward
from ..market.technical import summary as technical_summary
from ..memory.store import MemoryStore
from ..security.auth import AuthService, Permission, User

log = logging.getLogger(__name__)

DOMAIN_LABELS = {
    MemoryDomain.HISTORICAL: "SIMULATED (historical backtest)",
    MemoryDomain.FORWARD: "SIMULATED (walk-forward out-of-sample, historical data)",
    MemoryDomain.VIRTUAL: "SIMULATED (live virtual, estimated fills)",
    MemoryDomain.REAL: "ACTUAL BROKER FILLS",
}


class LoginBody(BaseModel):
    username: str
    password: str


class BacktestBody(BaseModel):
    source: str = "db"                    # "db" (stored ticks) | "synthetic" (test data, labeled)
    broker: str = "mock"
    symbol: str = "XAUUSD"
    start: datetime | None = None
    end: datetime | None = None
    params: dict = {}
    synthetic_ticks: int = 40_000
    learn: bool = True


class WalkForwardBody(BacktestBody):
    train_hours: float = 6
    validation_hours: float = 2
    test_hours: float = 2
    anchored: bool = False
    candidates: list[dict] = []


class EmergencyBody(BaseModel):
    active: bool
    reason: str = ""


class GrantBody(BaseModel):
    password: str
    phrase: str
    accounts: list[str]
    max_lots: float
    hours: float


class SignalAction(BaseModel):
    action: str
    token: str = ""


class DeviceTokenBody(BaseModel):
    device: str = ""


class AppState:
    """Runtime container. Optional services are attached by the runner when available."""

    def __init__(self, settings: Settings, store: MemoryStore | None = None):
        self.settings = settings
        self.store = store or MemoryStore(settings.database_url)
        self.auth = AuthService(settings, self.store)
        self.virtual_engines: dict[str, Any] = {}     # key -> LiveVirtualEngine
        self.specs: dict[tuple[str, str], SymbolSpec] = {}
        self.connectors: dict[str, Any] = {}          # broker -> MT5ReadOnlyConnector
        self.extras: dict[str, Callable[..., Any]] = {}  # optional providers: news, signals, maturity...


def create_app(state: AppState, dashboard_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="GOLD AI ADAPTIVE AGENTIC SCALPER", version="0.1.0")
    app.state.gold = state
    s = state

    def current_user(authorization: str = Header(default="")) -> User:
        token = authorization.removeprefix("Bearer ").strip()
        u = s.auth.user_from_token(token) if token else None
        if u is None:
            raise HTTPException(401, "not authenticated")
        return u

    def need(perm: Permission):
        def dep(u: User = Depends(current_user)) -> User:
            if not u.has(perm):
                raise HTTPException(403, f"missing permission {perm.value}")
            return u
        return dep

    def extra(name: str, *args, **kw):
        fn = s.extras.get(name)
        if fn is None:
            raise HTTPException(503, f"{name} service not configured")
        return fn(*args, **kw)

    # -- auth / health ---------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}

    @app.post("/api/auth/login")
    def login(body: LoginBody):
        u = s.auth.authenticate(body.username, body.password)
        if u is None:
            raise HTTPException(401, "invalid credentials")
        return {"token": s.auth.issue_token(u), "role": u.role}

    # -- overview -------------------------------------------------------------
    def overview_data() -> dict:
        return {
            "memory_counts": {d.value: s.store.count_trades(d) for d in MemoryDomain},
            "real_trading_enabled": s.settings.real_trading_enabled,
            "demo_execution_enabled": s.settings.demo_execution_enabled,
            "emergency_stop": bool(s.store.kv_get("emergency_stop", False)),
            "virtual_engines": [e.status() for e in s.virtual_engines.values()],
            "latest_runs": [_run_summary(r) for r in s.store.list_runs()[:10]],
        }

    @app.get("/api/overview")
    def overview(u: User = Depends(current_user)):
        return overview_data()

    @app.get("/api/brokers")
    def brokers(u: User = Depends(current_user)):
        out = []
        for broker, conn in s.connectors.items():
            row: dict = {"broker": broker}
            try:
                row.update(conn.health())
                a = conn.account()
                row.update(account=a.login, server=a.server, trade_mode=a.trade_mode, currency=a.currency)
            except Exception as e:  # report, never invent
                row.update(connected=False, error=str(e))
            row["symbols"] = [sp.symbol for (b, _), sp in s.specs.items() if b == broker]
            out.append(row)
        return out

    @app.get("/api/market/state")
    def market_state(u: User = Depends(current_user)):
        if not s.virtual_engines:
            raise HTTPException(503, "no live market engine running")
        eng = next(iter(s.virtual_engines.values()))
        st = eng.loop.market.state()
        lt = st.last_tick
        return {"broker": eng.spec.broker, "symbol": eng.spec.symbol, "ready": st.ready, "regime": st.regime,
                "features": st.features,
                "last_tick": None if lt is None else {"time": lt.time.isoformat(), "bid": lt.bid, "ask": lt.ask,
                                                      "spread": lt.spread}}

    @app.get("/api/analysis/technical")
    def technical_analysis(tf: str = Query("H1", pattern="^(M1|M5|M15|M30|H1|H4|D1)$"),
                           u: User = Depends(current_user)):
        if not s.virtual_engines:
            raise HTTPException(503, "no live market engine running")
        eng = next(iter(s.virtual_engines.values()))
        bars = list(eng.loop.market.mtf.bars.get(tf, []))
        return {"broker": eng.spec.broker, "symbol": eng.spec.symbol, **technical_summary(bars, tf)}

    # -- memory ----------------------------------------------------------------
    @app.get("/api/trades/{domain}")
    def trades(domain: MemoryDomain, limit: int = Query(200, le=5000), broker: str | None = None,
               u: User = Depends(current_user)):
        ts = s.store.load_trades(domain, broker=broker)
        m = json_safe(compute_metrics(ts))
        rows = []
        for t in ts[-limit:]:
            d = asdict(t)
            d["side"] = t.side.value
            d["exit_reason"] = t.exit_reason.value if t.exit_reason else None
            d["r_multiple"] = t.r_multiple
            d["context"] = {k: v for k, v in t.context.items() if k != "features"}
            rows.append(d)
        return {"domain": domain.value, "label": DOMAIN_LABELS[domain], "simulated": domain != MemoryDomain.REAL,
                "trades": rows, "metrics": m}

    @app.get("/api/runs")
    def runs(domain: MemoryDomain | None = None, u: User = Depends(current_user)):
        return [_run_summary(r) for r in s.store.list_runs(domain)]

    # -- research engines ----------------------------------------------------------
    def _load(body: BacktestBody):
        if body.source == "synthetic":
            ticks = list(synthetic_ticks(body.synthetic_ticks, drift=0.01, regime_switch_every=4000))
            return synthetic_spec(), ticks, SYNTHETIC_SOURCE
        spec = s.specs.get((body.broker, body.symbol))
        if spec is None:
            raise HTTPException(400, f"no broker specification loaded for {body.broker}/{body.symbol}")
        ticks = s.store.load_ticks(body.broker, body.symbol, body.start, body.end)
        if not ticks:
            raise HTTPException(400, "no stored ticks for that broker/symbol/period")
        return spec, ticks, "stored"

    @app.post("/api/backtest")
    def backtest(body: BacktestBody, u: User = Depends(need(Permission.BACKTEST))):
        spec, ticks, src = _load(body)
        r = run_backtest(s.settings, spec, ticks, params=StrategyParams(**body.params), learn=body.learn,
                         data_source=src, store=s.store)
        s.store.audit(u.username, "backtest", {"run_id": r.run_id, "source": src})
        return {"run_id": r.run_id, "label": DOMAIN_LABELS[MemoryDomain.HISTORICAL], "data_source": src,
                "synthetic_warning": src == SYNTHETIC_SOURCE and "synthetic random data: results say nothing "
                                                                "about real gold markets",
                "metrics": json_safe(r.metrics), "stats": asdict(r.stats), "model_start": r.model_start,
                "model_end": r.model_end, "data_hash": r.data_hash}

    @app.post("/api/walkforward")
    def walkforward(body: WalkForwardBody, u: User = Depends(need(Permission.FORWARD_VALIDATION))):
        spec, ticks, src = _load(body)
        cands = [StrategyParams(**c) for c in body.candidates] or [StrategyParams(**body.params)]
        cfg = WalkForwardConfig(timedelta(hours=body.train_hours), timedelta(hours=body.validation_hours),
                                timedelta(hours=body.test_hours), anchored=body.anchored)
        rep = run_walkforward(s.settings, spec, ticks, cands, cfg, store=s.store, data_source=src)
        s.store.audit(u.username, "walkforward", {"runs": rep.run_ids, "verdict": rep.verdict})
        return json_safe({
            "label": rep.label, "verdict": rep.verdict, "data_source": src, "oos_trades": rep.oos_trades,
            "oos_net": rep.oos_net, "oos_expectancy": rep.oos_expectancy,
            "selection_stability": rep.selection_stability, "overfit_flags": rep.overfit_flags,
            "run_ids": rep.run_ids,
            "folds": [{"index": f.fold.index, "selected": f.selected, "notes": f.notes,
                       "train": [x.isoformat() for x in f.fold.train],
                       "test": [x.isoformat() for x in f.fold.test],
                       "test_metrics": json_safe({k: v for k, v in f.test_metrics.items()
                                                  if k not in ("monthly", "by_regime")})}
                      for f in rep.folds],
        })

    # -- models -----------------------------------------------------------------------
    @app.get("/api/models")
    def models(u: User = Depends(current_user)):
        return s.store.list_models()

    @app.post("/api/models/{version}/promote")
    def promote(version: str, u: User = Depends(need(Permission.ADMIN))):
        return extra("promote", version, u)

    @app.post("/api/models/{version}/rollback")
    def rollback(version: str, u: User = Depends(need(Permission.ADMIN))):
        return extra("rollback", version, u)

    # -- risk / authorization -------------------------------------------------------
    @app.get("/api/risk")
    def risk(u: User = Depends(current_user)):
        states = {k: asdict(e.loop.risk.state) for k, e in s.virtual_engines.items()}
        return {"config": s.settings.risk.model_dump(), "state": json_safe_any(states),
                "emergency_stop": bool(s.store.kv_get("emergency_stop", False))}

    @app.post("/api/emergency-stop")
    def emergency(body: EmergencyBody, u: User = Depends(need(Permission.VIRTUAL_TRADING))):
        if not body.active and u.role != "owner":
            raise HTTPException(403, "only the owner can clear an emergency stop")
        s.auth.set_emergency_stop(u.username, body.active, body.reason)
        for e in s.virtual_engines.values():
            if body.active:
                e.loop.risk.trigger_emergency_stop(body.reason or "manual")
                e.emergency_close()
            else:
                e.loop.risk.clear_emergency_stop()
        if body.active and "emergency_close_real" in s.extras:
            s.extras["emergency_close_real"](u)
        return {"emergency_stop": body.active}

    @app.get("/api/authorization")
    def authorization(u: User = Depends(current_user)):
        g = s.store.kv_get("real_execution_grant")
        if g:
            g = dict(g, expires_at=datetime.fromtimestamp(g["expires"], timezone.utc).isoformat(),
                     active=g["expires"] > datetime.now(timezone.utc).timestamp())
        return {"real_trading_enabled": s.settings.real_trading_enabled,
                "demo_execution_enabled": s.settings.demo_execution_enabled,
                "grant": g, "account_allowlist": s.settings.account_allowlist}

    @app.post("/api/authorization/grant")
    def grant(body: GrantBody, u: User = Depends(need(Permission.ADMIN))):
        try:
            return s.auth.grant_real_execution(u, body.password, body.phrase, body.accounts, body.max_lots,
                                               body.hours)
        except (PermissionError, ValueError) as e:
            raise HTTPException(403, str(e))

    @app.post("/api/authorization/revoke")
    def revoke(u: User = Depends(need(Permission.ADMIN))):
        s.auth.revoke_real_execution(u.username, "revoked via API")
        return {"revoked": True}

    @app.get("/api/audit")
    def audit(limit: int = Query(200, le=2000), u: User = Depends(current_user)):
        return s.store.audit_log(limit)

    @app.get("/api/settings")
    def settings_view(u: User = Depends(current_user)):
        d = s.settings.model_dump()
        for k in ("secret_key", "telegram_bot_token", "whatsapp_token", "database_url", "quiver_api_token"):
            if d.get(k):
                d[k] = "***"
        return d

    @app.get("/api/ticks/stats")
    def tick_stats(u: User = Depends(current_user)):
        return s.store.tick_stats()

    # -- optional services wired by the runner --------------------------------------
    for path, name, perm in [
        ("/api/maturity", "maturity", None), ("/api/self-healing", "self_healing", None),
        ("/api/system/health", "system_health", None), ("/api/news", "news", None),
        ("/api/institutional", "institutional", None), ("/api/signals", "signals", None),
        ("/api/backups", "backups", None), ("/api/altdata", "altdata", None),
    ]:
        def make(name=name):
            def handler(broker: str | None = None, u: User = Depends(current_user)):
                return extra(name, broker=broker) if broker else extra(name)
            return handler
        app.get(path)(make())

    @app.post("/api/signals/{signal_id}/action")
    def signal_action(signal_id: str, body: SignalAction, u: User = Depends(need(Permission.SIGNALS))):
        return extra("signal_action", signal_id, body.action, body.token, u)

    # -- Android app: read-only device token for background signal alerts ---------------
    @app.post("/api/auth/device-token")
    def device_token(body: DeviceTokenBody, u: User = Depends(current_user)):
        return {"token": s.auth.issue_device_token(u, body.device), "expires_in": s.auth.DEVICE_TOKEN_TTL,
                "scope": "signals:read"}

    @app.post("/api/auth/device-token/revoke-all")
    def revoke_device_tokens(u: User = Depends(need(Permission.ADMIN))):
        s.auth.revoke_device_tokens(u)
        return {"ok": True}

    @app.get("/api/device/signals")
    def device_signals(authorization: str = Header(default="")):
        token = authorization.removeprefix("Bearer ").strip()
        if not token or s.auth.user_from_device_token(token) is None:
            raise HTTPException(401, "invalid or revoked device token")
        # Read-only view: action tokens stay in the dashboard session.
        return [{k: v for k, v in d.items() if k != "action_token"} for d in extra("signals")]

    @app.post("/api/backups")
    def make_backup(u: User = Depends(need(Permission.ADMIN))):
        return extra("create_backup", u)

    # -- live websocket ---------------------------------------------------------------
    @app.websocket("/ws/live")
    async def ws_live(ws: WebSocket, token: str = ""):
        if s.auth.user_from_token(token) is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        try:
            while True:
                await ws.send_json(json_safe_any({"type": "status", **overview_data()}))
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            return

    # -- static dashboard ----------------------------------------------------------------
    if dashboard_dir and Path(dashboard_dir).exists():
        root = Path(dashboard_dir).resolve()
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            f = (root / path).resolve()
            inside = f == root or root in f.parents  # never serve files outside the build folder
            return FileResponse(f if path and inside and f.is_file() else root / "index.html")

    return app


def _run_summary(r: dict) -> dict:
    m = r.get("metrics") or {}
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items() if k != "metrics"} | {
        "metrics": {k: v for k, v in m.items() if k not in ("monthly", "by_regime")},
        "label": DOMAIN_LABELS.get(MemoryDomain(r["domain"]), r["domain"]),
    }


def json_safe_any(x):
    if isinstance(x, dict):
        return {str(k): json_safe_any(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [json_safe_any(v) for v in x]
    if isinstance(x, datetime):
        return x.isoformat()
    if hasattr(x, "isoformat"):
        return x.isoformat()
    if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
        return None
    return x
