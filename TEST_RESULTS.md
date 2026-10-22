# Test results

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
| test_runtime.py | 1 |
| test_self_healing.py | 11 |
| test_symbols_and_connector.py | 7 |

## Not tested (cannot be, in this environment)
- Real MT5 terminals (Windows only) and the Exness/Equiti/MultiBank servers — only FakeMT5.
- MQL5 EA compilation.
- Real Telegram/WhatsApp/push delivery — HTTP mocked.
- Windows PowerShell scripts — not executed (no Windows host).

## Performance results
None. Every engine run so far used **synthetic random data** for testing mechanics. No real XAUUSD backtest,
walk-forward or virtual result exists yet, and none is claimed.
