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
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel

from ..agents.decision import StrategyParams
from ..brokers.mock_feed import SYNTHETIC_SOURCE, synthetic_spec, synthetic_ticks
from ..config import Settings
from ..domain import MemoryDomain, SymbolSpec
from ..engines.backtest import run_backtest
from ..engines.metrics import compute_metrics, json_safe
from ..engines.walkforward import WalkForwardConfig, run_walkforward
from ..instruments import canonical, instrument_for
from ..market.technical import summary as technical_summary
from ..memory.store import MemoryStore
from ..notifications.trade_alerts import profit_alerts
from ..security.auth import AuthService, Permission, User
from ..agents import strategy_selector as selector
from ..agents.leaderboard import leaderboard
from ..strategies import investigation

log = logging.getLogger(__name__)

DOMAIN_LABELS = {
    MemoryDomain.HISTORICAL: "SIMULATED (historical backtest)",
    MemoryDomain.FORWARD: "SIMULATED (walk-forward out-of-sample, historical data)",
    MemoryDomain.VIRTUAL: "SIMULATED (live virtual, estimated fills)",
    MemoryDomain.REAL: "ACTUAL BROKER FILLS",
}


class LaneBody(BaseModel):
    lane: str
    reason: str = ""


class CloseInvestigationBody(BaseModel):
    target: str
    reason: str


class LoginBody(BaseModel):
    username: str
    password: str
    remember: bool = False


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
        self.research_lanes: dict[str, Any] = {}      # key -> ResearchLaneEngine (simulation only)
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
        return {"token": s.auth.issue_token(u, remember=body.remember), "role": u.role, "remember": body.remember}

    @app.post("/api/auth/refresh")
    def refresh(authorization: str = Header(default="")):
        r = s.auth.refresh_token(authorization.removeprefix("Bearer ").strip())
        if r is None:
            raise HTTPException(401, "not authenticated")
        token, u = r
        return {"token": token, "role": u.role}

    # -- overview -------------------------------------------------------------
    def overview_data() -> dict:
        return {
            "memory_counts": {d.value: s.store.count_trades(d) for d in MemoryDomain},
            "real_trading_enabled": s.settings.real_trading_enabled,
            "demo_execution_enabled": s.settings.demo_execution_enabled,
            "emergency_stop": bool(s.store.kv_get("emergency_stop", False)),
            "virtual_engines": [e.status() for e in s.virtual_engines.values()],
            "research_lanes": [e.status() for e in s.research_lanes.values()],
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

    def style_of(e) -> str:
        return getattr(e, "style", "scalp")

    def engine_for(symbol: str | None, style: str = "scalp"):
        """Live engine for a broker symbol or canonical instrument name and trade style; gold by default."""
        if not s.virtual_engines:
            raise HTTPException(503, "no live market engine running")
        engines = [e for e in s.virtual_engines.values() if style_of(e) == style]
        if not engines:
            raise HTTPException(404, f"no {style} engine running")
        if not symbol:
            return engines[0]
        want = canonical(symbol) or symbol.upper()
        for e in engines:
            if e.spec.symbol == symbol or canonical(e.spec.symbol) == want:
                return e
        raise HTTPException(404, f"no live engine for {symbol}")

    @app.get("/api/instruments")
    def instruments(u: User = Depends(current_user)):
        """Instruments the live service analyses, with pip size and display digits for the apps."""
        out, seen = [], {}
        for e in s.virtual_engines.values():
            style = {"style": style_of(e), "ready": e.loop.market.ready, "open_positions": len(e.loop.sim.positions),
                     "timeframes": list(e.agent.params.timeframes),
                     "max_hold_seconds": e.agent.params.max_hold_seconds}
            k = (e.spec.broker, e.spec.symbol)
            if k in seen:   # one row per instrument; its trade styles are listed under "styles"
                seen[k]["styles"].append(style)
                continue
            inst = instrument_for(e.spec.symbol, s.settings)
            st = e.loop.market.state()
            lt = st.last_tick
            out.append({"broker": e.spec.broker, "symbol": e.spec.symbol,
                        "instrument": inst.name if inst else e.spec.symbol,
                        "asset_class": inst.asset_class if inst else "other",
                        "pip_size": inst.pip_size if inst else None,
                        "digits": inst.display_digits if inst else e.spec.digits,
                        "trades_weekends": inst.trades_weekends if inst else False,
                        "sessions_utc": e.loop.risk.cfg.allowed_sessions_utc,
                        "max_spread_points": e.loop.risk.cfg.max_spread_points,
                        "trade_mode": e.spec.trade_mode, "ready": st.ready, "regime": st.regime,
                        "last_tick": None if lt is None else {"time": lt.time.isoformat(), "bid": lt.bid,
                                                              "ask": lt.ask, "spread": lt.spread},
                        "open_positions": len(e.loop.sim.positions), "styles": [style]})
            seen[k] = out[-1]
        for row in out:
            row["open_positions"] = sum(x["open_positions"] for x in row["styles"])
        return json_safe_any(out)

    @app.get("/api/market/state")
    def market_state(symbol: str | None = None, style: str = Query("scalp", pattern="^(scalp|swing)$"),
                     u: User = Depends(current_user)):
        eng = engine_for(symbol, style)
        st = eng.loop.market.state()
        lt = st.last_tick
        return {"broker": eng.spec.broker, "symbol": eng.spec.symbol, "style": style_of(eng),
                "timeframes": list(eng.agent.params.timeframes), "ready": st.ready, "regime": st.regime,
                "features": st.features,
                "last_tick": None if lt is None else {"time": lt.time.isoformat(), "bid": lt.bid, "ask": lt.ask,
                                                      "spread": lt.spread}}

    @app.get("/api/analysis/technical")
    def technical_analysis(tf: str = Query("H1", pattern="^(M1|M5|M10|M15|M30|H1|H4|D1)$"),
                           symbol: str | None = None, u: User = Depends(current_user)):
        eng = engine_for(symbol)
        bars = list(eng.loop.market.mtf.bars.get(tf, []))
        return {"broker": eng.spec.broker, "symbol": eng.spec.symbol, **technical_summary(bars, tf)}

    # -- memory ----------------------------------------------------------------
    @app.get("/api/trades/{domain}")
    def trades(domain: MemoryDomain, limit: int = Query(200, le=5000), broker: str | None = None,
               symbol: str | None = None, style: str | None = Query(None, pattern="^(scalp|swing|research)$"),
               u: User = Depends(current_user)):
        """`symbol` is a broker symbol or a canonical instrument (EURUSD matches EURUSD.sd and EURUSDm).
        `style` keeps only scalping or swing trades (trades recorded before styles existed are scalping)."""
        names = None
        if symbol:
            want = canonical(symbol)
            names = [x for x in s.store.trade_symbols(domain) if x == symbol or (want and canonical(x) == want)]
        ts = s.store.load_trades(domain, broker=broker, symbols=names)
        if style:
            ts = [t for t in ts if t.context.get("style", "scalp") == style]
        m = json_safe(compute_metrics(ts))
        # Exploration trades (taken to gather data, not because the model expected a profit) are reported
        # apart, so their results are never read as the strategy's own performance.
        expl_ids = {t.trade_id for t in ts if t.context.get("exploration") or "[EXPLORATION]" in t.explanation}
        expl = [t for t in ts if t.trade_id in expl_ids]
        model = [t for t in ts if t.trade_id not in expl_ids]
        by_mode = {"exploration": json_safe(compute_metrics(expl)), "model_approved": json_safe(compute_metrics(model))}
        rows = []
        for t in ts[-limit:]:
            d = asdict(t)
            d["side"] = t.side.value
            d["exit_reason"] = t.exit_reason.value if t.exit_reason else None
            d["r_multiple"] = t.r_multiple
            inst = instrument_for(t.symbol)
            d["instrument"] = inst.name if inst else t.symbol
            d["pip_size"] = inst.pip_size if inst else None
            d["context"] = {k: v for k, v in t.context.items() if k != "features"}
            d["style"] = t.context.get("style", "scalp")
            d["exploration"] = t.trade_id in expl_ids
            inv = investigation.blocking(s.store, t.strategy_version)
            d["investigation"] = inv["target"] if inv else None
            rows.append(d)
        return {"domain": domain.value, "label": DOMAIN_LABELS[domain], "simulated": domain != MemoryDomain.REAL,
                "symbol": symbol, "style": style, "trades": rows, "metrics": m, "metrics_by_mode": by_mode}

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

    # -- strategy selection (agents/strategy_selector.py) -----------------------------
    def criteria():
        return selector.PromotionCriteria(**s.settings.promotion_criteria)

    def lane_or_404(key: str):
        lane = s.research_lanes.get(key)
        if lane is None:
            raise HTTPException(404, f"no research lane {key}")
        return lane

    @app.get("/api/agents/leaderboard")
    def agents_leaderboard(domain: str = Query("virtual", pattern="^(virtual|real)$"), u: User = Depends(current_user)):
        """Each AI agent and research lane by name and version, with its total recorded results."""
        d = MemoryDomain(domain)
        live = d == MemoryDomain.VIRTUAL      # running engines and lanes trade virtually; list them only there
        return json_safe_any({"domain": domain, "simulated": d != MemoryDomain.REAL, "agents": leaderboard(
            s.store.load_trades(d), [e.status() for e in s.virtual_engines.values()] if live else [],
            [l.status() for l in s.research_lanes.values()] if live else [])})

    @app.get("/api/strategies/scoreboard")
    def strategy_scoreboard(u: User = Depends(current_user)):
        """Every research lane's historical and forward evidence, whether it is eligible, and why not."""
        return json_safe_any({"criteria": asdict(criteria()),
                              "lanes": selector.scoreboard(s.store, s.research_lanes.values(), criteria())})

    @app.post("/api/strategies/promote")
    def strategy_promote(body: LaneBody, u: User = Depends(need(Permission.ADMIN))):
        lane = lane_or_404(body.lane)
        try:
            out = selector.promote(s.store, lane, criteria(), u)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        lane.refresh_champion()
        return json_safe_any(out)

    @app.post("/api/strategies/demote")
    def strategy_demote(body: LaneBody, u: User = Depends(need(Permission.ADMIN))):
        if u.role != "owner":
            raise HTTPException(403, "owner only")
        lane = lane_or_404(body.lane)
        out = selector.demote(s.store, lane, u.username, body.reason or "owner demotion")
        lane.refresh_champion()
        return {"demoted": out is not None}

    @app.get("/api/strategies/investigations")
    def investigations(u: User = Depends(current_user)):
        return investigation.listing(s.store)

    @app.post("/api/strategies/investigations/close")
    def close_investigation(body: CloseInvestigationBody, u: User = Depends(need(Permission.ADMIN))):
        try:
            return investigation.close_investigation(s.store, body.target, u, body.reason)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))

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
        for k in ("secret_key", "telegram_bot_token", "whatsapp_token", "database_url"):
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
        ("/api/backups", "backups", None),
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

    def _since(since: str | None) -> datetime | None:
        if not since:
            return None
        try:
            t = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "since must be an ISO 8601 time")
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

    # -- profit alerts: virtual and real trades that closed with a positive net result --------
    @app.get("/api/alerts/profit-closes")
    def profit_closes(limit: int = Query(30, ge=1, le=200), since: str | None = None,
                      u: User = Depends(current_user)):
        return profit_alerts(s.store, limit=limit, since=_since(since))

    @app.get("/api/device/profit-closes")
    def device_profit_closes(limit: int = Query(30, ge=1, le=200), authorization: str = Header(default="")):
        token = authorization.removeprefix("Bearer ").strip()
        if not token or s.auth.user_from_device_token(token) is None:
            raise HTTPException(401, "invalid or revoked device token")
        return profit_alerts(s.store, limit=limit)

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
                # overview_data reads the database; run it in a worker thread so a slow or locked database never
                # blocks the event loop (which also serves every page, script and API call).
                data = await asyncio.to_thread(overview_data)
                await ws.send_json(json_safe_any({"type": "status", **data}))
                await asyncio.sleep(2)
        except (WebSocketDisconnect, RuntimeError):
            # RuntimeError: the phone or browser dropped the connection (app closed, network switch) and the
            # server sends on a closed socket ("Unexpected ASGI message 'websocket.send'"). Nothing to do.
            return

    # -- static dashboard ----------------------------------------------------------------
    if dashboard_dir and Path(dashboard_dir).exists():
        root = Path(dashboard_dir).resolve()
        app.mount("/assets", _BuildAssets(directory=root / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            f = (root / path).resolve()
            inside = f == root or root in f.parents  # never serve files outside the build folder
            if path and inside and f.is_file() and f.name != "index.html":
                return FileResponse(f)
            # index.html names the current build's scripts: never let a browser or the app keep an old copy,
            # or after an update it asks for scripts that no longer exist and pages fail to open.
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app


# A page script from an earlier build: answering with this instead of a 404 makes a stale page (an app or
# browser that kept an old cached index.html/index.js across a redeploy) reload and pick up the current build.
_STALE_CHUNK_JS = ("try{var k='goldai:stale-reload',t=+sessionStorage.getItem(k)||0;"
                   "if(Date.now()-t>60000){sessionStorage.setItem(k,String(Date.now()));location.reload();}}"
                   "catch(e){location.reload();}\nexport default null;\n")


class _BuildAssets(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404 and path.endswith(".js"):
                return Response(_STALE_CHUNK_JS, media_type="text/javascript",
                                headers={"Cache-Control": "no-store"})
            raise


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
