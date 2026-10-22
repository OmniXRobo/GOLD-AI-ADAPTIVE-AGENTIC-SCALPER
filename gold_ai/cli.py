"""Command-line entry point: `python -m gold_ai <command>`.

Commands
  create-user     create the owner/operator/viewer account (prompts for password)
  import-ticks    load an MT5 tick export / CSV into persistent storage
  backtest        Engine A on stored ticks
  walkforward     Engine B on stored ticks
  serve           start the API/dashboard (+ MT5 collector and live virtual engine with --mt5)
"""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
import threading
from datetime import datetime, timedelta

from .agents.decision import StrategyParams
from .config import load_settings
from .domain import SymbolSpec
from .engines.backtest import run_backtest
from .engines.metrics import json_safe
from .engines.walkforward import WalkForwardConfig, run_walkforward
from .market.ingest import QualityReport, load_tick_file
from .memory.store import MemoryStore
from .security.auth import AuthService

log = logging.getLogger("gold_ai")


def _spec_from_store(store: MemoryStore, broker: str, symbol: str) -> SymbolSpec:
    d = store.kv_get(f"spec:{broker}:{symbol}")
    if not d:
        sys.exit(f"No symbol specification stored for {broker}/{symbol}. Run `serve --mt5` once to capture "
                 f"it from the broker, or `import-spec` with the EA's JSON snapshot.")
    d["filling_modes"] = tuple(d.get("filling_modes", ()))
    return SymbolSpec(**d)


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="gold_ai")
    ap.add_argument("--config", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("create-user")
    u.add_argument("username")
    u.add_argument("--role", default="owner", choices=["owner", "operator", "viewer"])

    it = sub.add_parser("import-ticks")
    it.add_argument("path")
    it.add_argument("--broker", required=True)
    it.add_argument("--symbol", required=True)
    it.add_argument("--format", default="auto", choices=["auto", "mt5", "csv"])
    it.add_argument("--tz-offset-hours", type=float, default=0.0, help="server time offset from UTC")

    isp = sub.add_parser("import-spec", help="store a symbol spec from the EA's *_spec.json snapshot")
    isp.add_argument("path")
    isp.add_argument("--broker", required=True)
    isp.add_argument("--commission-per-lot-side", type=float, default=0.0)

    for name in ("backtest", "walkforward"):
        p = sub.add_parser(name)
        p.add_argument("--broker", required=True)
        p.add_argument("--symbol", required=True)
        p.add_argument("--start")
        p.add_argument("--end")
        p.add_argument("--params", default="{}", help="JSON StrategyParams overrides")
        if name == "walkforward":
            p.add_argument("--train-days", type=float, default=30)
            p.add_argument("--validation-days", type=float, default=7)
            p.add_argument("--test-days", type=float, default=7)
            p.add_argument("--anchored", action="store_true")

    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--mt5", action="store_true", help="connect to the local MT5 terminal (read-only)")
    sv.add_argument("--terminal-path", default=None)
    sv.add_argument("--symbol", default=None, help="override automatic gold symbol discovery")
    sv.add_argument("--dashboard", default="dashboard/dist")

    a = ap.parse_args(argv)
    settings = load_settings(a.config)
    store = MemoryStore(settings.database_url)

    if a.cmd == "create-user":
        pw = getpass.getpass("Password (min 10 chars): ")
        AuthService(settings, store).create_user(a.username, pw, a.role, actor="cli")
        print(f"created {a.role} {a.username}")
        return 0

    if a.cmd == "import-ticks":
        rep = QualityReport()
        ticks = load_tick_file(a.path, a.format, a.tz_offset_hours, rep)
        n = store.save_ticks(a.broker, a.symbol, ticks, source="mt5_export" if a.format != "csv" else "csv")
        store.audit("cli", "import_ticks", {"path": a.path, "rows": rep.rows, "accepted": n})
        print(json.dumps({"stored": n, **{k: v for k, v in rep.__dict__.items()}}, default=str, indent=2))
        return 0

    if a.cmd == "import-spec":
        raw = json.load(open(a.path))
        swap_modes = {1: "points"}
        spec = dict(broker=a.broker, symbol=raw["symbol"], digits=raw["digits"], point=raw["point"],
                    tick_size=raw["tick_size"], tick_value=raw["tick_value"], contract_size=raw["contract_size"],
                    volume_min=raw["volume_min"], volume_max=raw["volume_max"], volume_step=raw["volume_step"],
                    stops_level_points=raw["stops_level"], freeze_level_points=raw["freeze_level"],
                    swap_long=raw["swap_long"], swap_short=raw["swap_short"],
                    swap_mode=swap_modes.get(raw["swap_mode"], "money"),
                    commission_per_lot_side=a.commission_per_lot_side,
                    currency_base=raw["currency_base"], currency_profit=raw["currency_profit"])
        store.kv_set(f"spec:{a.broker}:{raw['symbol']}", spec)
        print(f"stored spec for {a.broker}/{raw['symbol']}")
        return 0

    if a.cmd in ("backtest", "walkforward"):
        spec = _spec_from_store(store, a.broker, a.symbol)
        ticks = store.load_ticks(a.broker, a.symbol, _dt(a.start), _dt(a.end))
        if not ticks:
            sys.exit("no stored ticks for that broker/symbol/period")
        params = StrategyParams(**json.loads(a.params))
        if a.cmd == "backtest":
            r = run_backtest(settings, spec, ticks, params=params, store=store, data_source="stored")
            print(json.dumps({"run_id": r.run_id, "metrics": json_safe(r.metrics)}, indent=2, default=str))
        else:
            cfg = WalkForwardConfig(timedelta(days=a.train_days), timedelta(days=a.validation_days),
                                    timedelta(days=a.test_days), anchored=a.anchored)
            rep = run_walkforward(settings, spec, ticks, [params], cfg, store=store, data_source="stored")
            print(json.dumps({"label": rep.label, "verdict": rep.verdict, "oos_trades": rep.oos_trades,
                              "oos_net": rep.oos_net, "flags": rep.overfit_flags}, indent=2))
        return 0

    if a.cmd == "serve":
        import uvicorn

        from .runtime import build_runtime
        app, workers = build_runtime(settings, store, use_mt5=a.mt5, terminal_path=a.terminal_path,
                                     symbol=a.symbol, dashboard_dir=a.dashboard)
        for w in workers:
            threading.Thread(target=w, daemon=True).start()
        uvicorn.run(app, host=a.host, port=a.port)
        return 0
    return 1
