# Test results



## 2026-10-22 — session 2c (cloud container)
- `python -m pytest -q` → **172 passed, 1 skipped** (adds tests/test_technical.py: RSI reference value from
  Wilder's example, insufficient-bar handling, trend direction, endpoint 503/422).
- Dashboard `tsc --noEmit` and build OK. New screens checked in Chromium at 390×844 and 1440×900 against a local
  preview server fed with synthetic placeholder values (layout check only; nothing from it is recorded anywhere).
- Android 1.1.0 (versionCode 2): built, aligned, `apksigner verify` OK, same signer certificate as 1.0.0.
  Not yet run on a device.

## 2026-10-22 — session 2b (cloud container, Linux, Python 3.13)
- `python -m pytest -q` → **165 passed, 1 skipped** (new: device-token scope/revocation, signal action JSON body,
  static file containment).
- Dashboard: `npx tsc --noEmit` and `npm run build` OK; pages split into chunks (entry + React ~83 kB gzip, charts
  108 kB gzip loaded with the first chart page). Checked in Chromium at 1440×900 and 390×844 against a local
  server with an empty database (no live engine, so the price ticker was hidden and Overview showed the 503 reason).
- Android: `android/build.sh` built `gold-ai.apk` (versionCode 1, minSdk 24, targetSdk 34) against the Robolectric
  Android 13 jar; `zipalign -c` OK; `apksigner verify` OK (v2 + v3). Not installed on a device or emulator (none
  available in the container).

## 2026-10-22 — session 2 (owner's Windows VPS: Windows Server 2022, Python 3.12.10)
- `deploy\windows\install.ps1` (after fixing its Python launcher pin) → `python -m pytest -q` **155 passed, 1 skipped**,
  matching session 1. After the server-time fix and its 4 new tests: **159 passed, 1 skipped**.
- MT5 terminals found: `C:\Program Files\MT5_1` (build 6241, running, logged in to **MetaQuotes-Demo**, demo account,
  hedging) and `C:\Program Files\MT5_2` (build 6244, not logged in). No Exness / Equiti / MultiBank login yet.
- Read-only connector on MetaQuotes-Demo: connect OK, account detected as `demo`, broker `generic`; gold discovery
  validated `XAUUSD` (base XAU, profit USD, contract 100, 2 digits, FOK/IOC, market execution, swap -12.6/-4.6 points,
  commission not reported by symbol info). Real demo quotes read (e.g. bid 4076.99 / ask 4077.36 at 13:29:55 UTC).
- **Defect found and fixed:** MT5 stamps ticks in broker server time (MetaQuotes-Demo = UTC+3). Before the fix the
  latest tick was labelled 3 h in the future and the collector's range queries returned ticks 3 h old. After the fix
  the measured offset is UTC+3.0 h, the latest tick's age is ~0.1 s, and a 2-minute range returns 2 minutes of ticks.
- `GoldAIBridge.mq5` compiled with MetaEditor (build 6241): **0 errors, 1 warning** (version string format, MQL5 Market
  only). Not attached to a chart yet; the Python collector does not need it.
- Service (`start.ps1`, read-only `--mt5`, real and demo execution disabled) running against MT5_1: tick collector
  stored 37,252 real XAUUSD demo ticks in its first ~2 minutes (1 h backfill + live). The live virtual engine started
  and is warming up (needs 20 M5 bars ≈ 100 min of live ticks before its first decision). No virtual trade yet.
- **Equiti demo (MT5_2, EquitiSecurities-Demo, demo/hedging), added 13:57 UTC:** broker identified as `equiti`.
  Discovery chose `XAUUSD.sd` (tradeable); plain `XAUUSD` exists but has trading disabled. Spec: 2 digits, contract
  100, tick value 1.0, IOC only, market execution, swap -11.41/+6.427 points, commission not reported by symbol info
  (check the account type's commission). Server offset measured UTC+3.0 h; latest tick age ~0 s (bid 4057.76 /
  ask 4058.03 at 13:57:08 UTC). Second read-only service on port 8001 stored 63,528 Equiti ticks in its first
  minute (1 h backfill + live). Virtual engine warming up; no decision or trade yet.
- **Later in session 2 (Equiti only, owner decision):** Node.js 22.20.0 installed; dashboard `npm ci`, `tsc --noEmit`
  and `npm run build` OK (697 kB JS bundle) and served at http://127.0.0.1:8001. Runtime workers now run under the
  Supervisor and the virtual engine warms up from stored ticks: tests **160 passed, 1 skipped**. After restart the
  engine replayed 82,305 stored Equiti ticks (12:57–14:10 UTC); that is under the 100 minutes needed, so it was not
  ready yet. Still no decision or virtual trade at that point.
- Service moved to the logon scheduled task `GoldAI-Equiti` (MT5_2, port 8001; restart every minute on failure);
  `/api/health` OK and the owner signed in to the dashboard. Scheduled self-healing and log token redaction added:
  tests **162 passed, 1 skipped**. Found that uvicorn logged the dashboard session token in WebSocket URLs; now
  redacted, and the two existing log files were scrubbed.
- **First research on real Equiti ticks (1,973,343 ticks copied read-only from the terminal, 2026-10-18 21:00 to
  2026-10-22 15:00 UTC, about 3.5 trading days; backtests use Equiti's live spec, commission 0 as reported):**
  - Backtest, default params (exploration 0): **0 trades** — a fresh model waits without evidence. 614 s.
  - Backtest, `exploration_rate=0.2`: 10 trades, 2 wins / 8 losses, net **-271.90 USD** on 10,000 (-2.7%),
    profit factor 0.25, expectancy -27.19 USD/trade, max drawdown 2.72%, spread 20.45 + slippage 15.35 USD.
    Exits: 7 stop loss, 1 trailing, 1 take profit, 1 expiry. 610 s. Run `backtest-e42ff115cdff`.
  - Walk-forward (train 1 d / validation 6 h / test 6 h, exploration 0.2): verdict **insufficient_data**, 0 OOS trades.
  - Interpretation: there is no evidence of an edge yet; the sample is far too small to judge. Not a performance claim.
- Live virtual (Equiti): first trade BUY 0.03 @ 4058.25 at 14:40 UTC closed on time expiry at 15:40 UTC,
  net -18.18 USD (exploration trade, estimated fill).
- Economic calendar: GoldAICalendar.mq5 compiled (0 errors, 0 warnings), attached in MT5_1 via start config;
  exported 346 events; service loaded 170 events in its 7-day window. Tests **164 passed, 1 skipped**.


## 2026-10-22 — session 1 (Linux cloud container, Python 3.13, Node 22)
- `python -m pytest -q` → **155 passed, 1 skipped** (skip = PostgreSQL test without `GOLDAI_TEST_PG_URL`).
- With `GOLDAI_TEST_PG_URL=postgresql+psycopg://...` against a local PostgreSQL 16 → **156 passed**.
- Dashboard: `npm install` (0 vulnerabilities after upgrading react-router-dom/vite), `npx tsc --noEmit` OK,
  `npm run build` OK (single 697 kB JS bundle, 203 kB gzipped).
- Browser smoke test (headless Chromium, API + FakeMT5 live feed, all 24 routes at 1280px and 375px):
  no console/page errors, no HTTP ≥400, no horizontal scroll. It found two defects, both fixed and re-verified:
  WebSocket handshake failed because uvicorn lacked a WebSocket library (now `uvicorn[standard]`), and the
  System Health page crashed rendering an object (backend payload adapted to the dashboard contract).

| File | Tests |
|---|---|
| test_api.py | 8 |
| test_backup.py | 5 |
| test_costs_and_simulator.py | 8 |
| test_engines.py | 11 |
| test_execution.py | 21 |
| test_health.py | 6 |
| test_ingest_collector.py | 4 |
| test_institutional.py | 8 |
| test_market.py | 5 |
| test_maturity.py | 7 |
| test_memory_and_auth.py | 9 |
| test_news.py | 24 |
| test_notifications.py | 13 |
| test_postgres.py | 1 |
| test_risk.py | 7 |
| test_runtime.py | 4 |
| test_self_healing.py | 11 |
| test_symbols_and_connector.py | 11 |

## Not tested (cannot be, in this environment)
- Real MT5 terminals (Windows only) and the Exness/Equiti/MultiBank servers — only FakeMT5.
- MQL5 EA compilation (done in session 2 on the VPS).
- Real Telegram/WhatsApp/push delivery — HTTP mocked.
- Windows PowerShell scripts — not executed in session 1 (install.ps1 and start.ps1 run on the VPS in session 2).

## Performance results
See session 2 above for the first runs on real Equiti ticks (no edge shown; sample too small). Session 1 runs used synthetic data only.
walk-forward or virtual result exists yet, and none is claimed.
