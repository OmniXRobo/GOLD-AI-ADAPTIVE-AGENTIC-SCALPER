# Project status — 2026-10-26 (session 4, root-cause audit)

**Real-money execution: DISABLED. Demo execution: DISABLED.** No order has been sent to any broker.
No strategy has shown an edge after costs (168 virtual trades, net -533.99 USD; all exploration trades).

## Session 5b (app pages stuck loading, 2026-10-27)
- Cause: the live-status websocket read the database on the server's event loop every 2 s per open screen; with
  the large, busy VPS database each read stalled every page, script and API call. Fixed by reading in a worker
  thread. Also: index.html is never cached, polling no longer piles up, GETs time out after 30 s, and a page that
  fails to load shows Retry. Needs `git pull`, `npm run build` and a service restart on the VPS.

## Session 5 (profit alerts, 2026-10-27)
- Owner asked for an in-app notification when a trade closes in profit. Dashboard: a bell in the header with an
  unread count, the last profitable closes, and a pop-up for each new one. Android 1.5.0 source: a separate
  "Trades closed in profit" notification. Each alert says VIRTUAL (estimated fills) or REAL (broker fill) and
  marks exploration trades. Read-only; nothing is executed. 261 tests pass. APK still to be built with the key.

## Session 4 (root-cause audit of the losing virtual strategy, 2026-10-26)
- Owner reported 34 virtual trades, 32.4% win rate, −991 pips, PF ~0.50 (not yet reproduced from the DB).
  Code audit of 24 items in docs/ROOT_CAUSE_AUDIT.md. Main finding: every virtual trade so far was an
  exploration trade of two hard-coded candidate rules (immature model, exploration 0.2), which had no
  research evidence. The exit design gives ~50% wins of ~1R on a random walk, so a 32% win rate points to
  entries worse than random, not costs (~0.05R) or exits.
- The adaptive strategy family (`family:adaptive-v1`, all `strat-`/`heal-` versions) is under investigation:
  promotion, rollback, MT5 execution (demo included) and signals are blocked; virtual trading continues;
  only the owner can close it. Models are backed up in the registry at engine start.
- Fixed: EV uses realized win/loss size per direction; trades store initial stop and MFE/MAE; `/api/trades`
  reports exploration apart; new read-only `audit-trades` CLI. 253 tests pass.

## Session 3b (first real-data research, 2026-10-25)
- Stage 1 deployed on the VPS (239 tests pass). `research` ran on 3,285,567 real Equiti XAUUSD.sd ticks
  (2026-10-18 → 2026-10-23, ~5 trading days). Report committed as-is in docs/research/ with an interpretation.
- Result: every setup `insufficient_data` (0–11 test trades, 30 needed); no champion, nothing promoted. The most
  common rejection was round-trip costs above 0.25R of the stop; only spread/ATR and Bollinger bandwidth
  percentile carried stable information. The +0.91R of the incumbent S/R rejection on 11 test trades flipped
  sign from validation (−0.44R) and is not evidence.
- Research now streams ticks from the database in 6-hour chunks, so weeks of history can be evaluated.
  Next: backfill weeks of ticks on the VPS, then test cost-aware variants (volatility-to-spread filter, M5/M15 stops).

## Session 3 (agentic XAUUSD redesign, cloud container)
- Owner asked for a genuine evidence-driven agentic gold scalper. Design written: docs/AGENTIC_REDESIGN.md
  (gap analysis of what exists, architecture and agent roles, data sources with licensing/latency/indicative
  costs, database design, research and validation plan, risk-engine spec R1-R23, degraded operation, six stages
  with acceptance criteria). Live risk settings stay illustrative until the owner gives account size and risk
  tolerance.
- Stage 1 built and tested on synthetic data only: indicator library (EMA, ADX/DI, Bollinger %B/bandwidth,
  tick-volume VWAP and profile, swings, liquidity sweeps); strategy library (trend pullback, breakout, failed
  breakout, range mean reversion, liquidity sweep, the two incumbent candidates, random baseline); research
  harness (`python -m gold_ai research`) with chronological train/validation/test, the same fills/costs/risk
  as the engines, matched random-entry baselines, bootstrap intervals and conservative verdicts, results in
  Memory A (`kind=research`); feature evaluation (out-of-sample information, redundancy pruning).
- Decision agent: expected value is now computed after round-trip costs; WAIT reasons start with "NO TRADE".
- Risk engine v2 (applies to every engine, including the live virtual engines after deploy): weekly loss limit,
  3-loss cooldown, no re-entry for 5 min after a loss, 20 trades/day and 2 min spacing, abnormal volatility and
  spread filters, latency and margin checks, EV-after-cost gate, start-up observation window for demo/real,
  duplicate prevention, reconciliation after reconnect, stop may only tighten, manual overrides recorded but never
  applied, owner sessions in Dubai time, rule-set version on every verdict. Fixed: daily limits now roll over on
  the first tick of a new day (before, a daily block lasted until some trade closed).
- Not done yet: real-data research run (needs the VPS), Stages 2-6. No live behaviour was enabled.
## Session 2g (scalping and swing signals)
- Each instrument now runs two virtual engines: **scalping** (M1/M5/M15, SL 1.5× M5 ATR, TP 1.5R, held ≤ 1 h)
  and **swing** (M15/H1/H4, SL 1.5× H1 ATR, TP 2R, held ≤ 3 days). Separate virtual accounts, models, trade
  history (Memory C `context.style`), signals and self-healing. Shown in Signals, Results, Autopilot and app
  alerts (Android 1.4.0 source). See docs/TRADE_STYLES.md.
- Engines seed higher-timeframe bars from the broker at warm-up, so new symbols have H1/H4/D1 history at once.
- Fixed: an owner-promoted version was never loaded into the live engine (now applied and persisted, scoped to
  its symbol and style); live-status websocket crashed when the phone disconnected; concurrent signals could
  overwrite each other; dashboard reads moved the model's tick-acceleration input; empty Domain column on Signals.
- No swing results exist yet. Signals and virtual only; nothing is executed.

## Session 2f (BTCUSD and major forex pairs)
- Owner asked for BTCUSD and major currency pair signals. The live service now runs one collector, live virtual
  engine and learning memory per instrument: XAUUSD, BTCUSD, EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD,
  NZDUSD (whichever the broker offers). Per-instrument pip size, spread/slippage limits, trading hours, news
  currencies and swap rules (docs/INSTRUMENTS.md); contract values still come from broker metadata.
- Dashboard: market chips on Home (live price), Signals, Results (pips per instrument) and Analysis; `/api/instruments`.
  Android 1.3.0 source (alert prices with the right decimals); APK still to be built on the VPS with the signing key.
- Signals and virtual trades only; nothing is executed. No results exist yet for the new instruments.

## Session 2e (more reference-app screens)
- Results: period chips (today, yesterday, 7 days, month, all), gain/loss pips banner, stat tiles, green/red trade
  cards with exit reason and time held. Home: next medium/high impact calendar event with countdown. Autopilot:
  trading performance summary of the virtual account. Fixed a CSS clash that underlined green numbers. App 1.2.1.

## Session 2d (ideas from a reference gold-signal site)
- New dashboard pages: Results (win rate, pips won/lost, today / 7 days / month, trade history, virtual or real
  account), Learn (how it works, lot size and risk calculator, money management, FAQ), and a public landing page
  shown before sign-in. All figures come from the app's own recorded trades; no performance claims anywhere.
- Not built, waiting for the owner: paid packages, copy trading/rewards, multi-asset signals, profit lock,
  community links (TASK_QUEUE.json, NEXT_ACTIONS.md). Android app 1.2.0.

## Session 2c (simplified UI)
- New default look (cream and gold) with Home, Autopilot, Analysis, Practice; older pages under Advanced.
- Android app 1.1.0 built (same key as 1.0.0, installs as an update). Strategy ideas from the reference app are
  written up in docs/STRATEGY_IDEAS.md; engine changes wait for the owner.

## Session 2b (dashboard UI and Android app)
- Dashboard redesigned (dark gold theme, icons, live price from real ticks only, mobile layout) and code-split.
- Android app in `android/` (dashboard + read-only signal alerts). APK built and signature-verified; **not yet tested
  on a phone**. Phone access needs Tailscale on the VPS and phone (docs/ANDROID_APP.md).
- Fixed the signal Approve/Reject endpoint (was always rejected with 422). Tests 165 passed / 1 skipped.
- After merging, the VPS needs `git pull` and `npm run build` in `dashboard/` to serve the new UI.

## Session 2 (VPS)
- Installed on the VPS at `C:\Users\Administrator\Desktop\GOLD-AI-ADAPTIVE-AGENTIC-SCALPER` (Python 3.12.10, venv).
  Tests 159 passed / 1 skipped.
- **Owner decision (14:03 UTC): focus on Equiti only for now.** One read-only service runs: port 8001 on **Equiti demo**
  (MT5_2, XAUUSD.sd). The MetaQuotes-Demo service (port 8000) was stopped; its collected ticks stay in the DB:
  real XAUUSD demo ticks are being collected; the live virtual engine is warming up. See TEST_RESULTS.md.
- Fixed: broker server time → UTC conversion in the MT5 connector (ticks were 3 h off); Windows install/start scripts.
- Added: Supervisor-run workers (crash restart with backoff), virtual-engine warm-up from stored ticks, dashboard
  built and served by the service (Node 22 on the VPS). register-task.ps1 takes -Port. Auto-start task **GoldAI-Equiti** registered (owner OK) and running the service.
- Added: daily scheduled self-healing check on Equiti virtual trades; session tokens redacted from logs.
- MQL5 bridge compiled (0 errors).
- Still needed from the owner: Exness and MultiBank demo logins, tick exports, and an owner account
  (`create-user owner` asks for a password, so the owner runs it). See BLOCKERS.md.


## State
- Code for every component in the master plan exists with automated tests: 159 passed / 1 skipped
  (156/156 with PostgreSQL). See TEST_RESULTS.md.
- Verified only against simulated/fake brokers (FakeMT5) and synthetic data. Nothing has been verified on
  Exness, Equiti or MultiBank yet — that requires the owner's Windows VPS (BLOCKERS.md).
- Execution adapter exists and is tested with a fake MT5 module; it is intentionally not wired into the service.

## Where the code lives
- GitHub: https://github.com/OmniXRobo/GOLD-AI-ADAPTIVE-AGENTIC-SCALPER (branch `main`, public).
- Backup copy: git bundle in the project files folder `gold-ai-scalper/gold-ai-scalper.bundle`.

## Next task
First `todo` in TASK_QUEUE.json by priority: **T-STAGE1-REAL-RESEARCH** (VPS), then Stage 2. Owner-blocked tasks with priority 1:
T-VERIFY-BROKERS and T-REAL-DATA-RESEARCH.
