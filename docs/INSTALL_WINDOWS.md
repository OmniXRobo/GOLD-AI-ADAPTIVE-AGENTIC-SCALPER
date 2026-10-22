# Windows VPS installation

## 1. Prerequisites
- Windows Server 2019+/Windows 10+ VPS, 4 GB RAM minimum (8 GB with PostgreSQL and several terminals).
- Python 3.11+ (python.org installer, "Add to PATH"). On Windows Server 2022 the per-user install failed
  (MSI error 0x80070003); the all-users install (`InstallAllUsers=1 TargetDir=C:\Python312`) worked.
- Node.js 20+ (only to build the dashboard).
- Git for Windows.
- One MetaTrader 5 terminal per broker account, installed to separate folders
  (e.g. `C:\MT5\Exness`, `C:\MT5\Equiti`, `C:\MT5\MultiBank`) using each broker's installer.
  In each terminal: Tools → Options → Expert Advisors → tick "Allow algorithmic trading" ONLY if you later
  authorize execution; the read-only data path does not need it.

## 2. Install
```powershell
git clone <repo-or-bundle> C:\GoldAI ; cd C:\GoldAI
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
notepad config.local.json     # set secret_key (64 random chars), database_url
.\.venv\Scripts\python.exe -m gold_ai --config config.local.json create-user owner
```

## 3. Database
- Default: SQLite at `data\gold_ai.db` (fine for one VPS).
- PostgreSQL (recommended for production): install PostgreSQL 16 (needs admin once), create database `goldai`
  and user, then `install.ps1 -Postgres` and set
  `"database_url": "postgresql+psycopg://goldai:<pw>@127.0.0.1:5432/goldai"`.
  Optional TimescaleDB: `SELECT create_hypertable('ticks','time', migrate_data => true);` (requires dropping the
  integer primary key constraint first; do this before collecting large volumes).

## 4. MT5 terminals
- Log each terminal into its account (demo first). Keep the terminal running.
- Start GOLD AI against a terminal (one process per terminal, different ports):
  `deploy\windows\start.ps1 -TerminalPath "C:\MT5\Exness\terminal64.exe" -Port 8000`
- The gold symbol is discovered from broker metadata; override with `-Symbol XAUUSDm` if needed.
- Optional EA bridge: copy `mql5\GoldAIBridge.mq5` to `<terminal data folder>\MQL5\Experts`, compile in
  MetaEditor, attach to an XAUUSD chart. It writes ticks to Common\Files; import with
  `python -m gold_ai import-ticks <file> --broker exness --symbol XAUUSDm --format csv --tz-offset-hours 2`.

## 5. Historical data
Export ticks in MT5 (View → Symbols → Ticks → select range → Request → Export) and import:
`python -m gold_ai import-ticks XAUUSD_ticks.csv --broker exness --symbol XAUUSDm --tz-offset-hours 2`
Then `python -m gold_ai backtest --broker exness --symbol XAUUSDm` / `walkforward ...`.

Or copy the broker's tick history straight from a logged-in terminal (read-only; stops at the first tick
already stored, so it never duplicates the live collector):
`python -m gold_ai --config config.local.json backfill-ticks --terminal-path "C:\Program Files\MT5_2\terminal64.exe" --days 5`
Roughly 0.5-0.6 M XAUUSD ticks per trading day on Equiti; a backtest over ~2 M ticks takes about 10 minutes.
A fresh model waits without evidence, so a first backtest needs `--params '{"exploration_rate": 0.2}'`
to take any trades at all (exploration trades are flagged and never sent as signals).

## 5b. Economic calendar (news blackout)
Compile `mql5\GoldAICalendar.mq5` and attach it to any chart in one terminal (no trading functions). Every
15 minutes it writes `%APPDATA%\MetaQuotes\Terminal\Common\Files\goldai_calendar.csv` (UTC times, high/medium/low
impact). List that path under `news_calendar_files` in `config.local.json`; the service re-reads it every
5 minutes and blocks new virtual entries around high-impact events.
To attach it without the GUI, start the terminal with a start config containing
`[StartUp]` / `Expert=GoldAICalendar` / `Symbol=XAUUSD` / `Period=H1` (`terminal64.exe /config:<file>`).

## 6. Run as a service
`deploy\windows\register-task.ps1 -TerminalPath "C:\MT5\Exness\terminal64.exe"` registers a per-user scheduled
task (start at logon, hidden window). `start.ps1` restarts the service 10 s after it exits and logs each exit
to `logsestarts.log`; Task Scheduler's own restart setting does not react to exit codes. Do not run it in a
visible console you might close: closing the window ends the service. Add `-Port 8001` etc. per terminal.
Keep the VPS user logged on (MT5 requires a session).
Health: `deploy\windows\healthcheck.ps1`. Logs: `logs\`. Diagnostics zip: `deploy\windows\collect-logs.ps1`.

## 7. Backups
`deploy\windows\backup.ps1` writes a timestamped, checksummed copy to `backups\`. Copy backups off the VPS.

## 8. Firewall / access
- The API binds to 127.0.0.1 by default. For remote dashboard access, prefer an SSH tunnel or a VPN
  (WireGuard/Tailscale) over opening a port. If you must expose it, put it behind a reverse proxy with TLS
  (Caddy/IIS) and allow only your IPs in Windows Defender Firewall (admin needed for firewall rules).
- Never expose the MT5 terminal or database ports.

## Admin rights summary
Needed only for: PostgreSQL install, firewall rules, system-wide services. Everything else runs per-user.
