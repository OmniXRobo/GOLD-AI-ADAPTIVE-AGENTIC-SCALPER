# Agentic XAUUSD redesign — design and staged plan

Status: written 2026-10-25. Stage 1 implemented and tested on synthetic data only (see §7); the real-data research run is next.
Real-money execution stays **disabled**. Nothing in this document is a performance claim: no strategy in
this project has shown an edge after costs yet (TEST_RESULTS.md, 2026-10-25: 168 virtual trades, net -533.99 USD,
all exploration trades; 4 challenger parameter sets failed to beat the incumbent).

The goal is an XAUUSD scalping system that observes, researches, evaluates evidence, plans, manages risk, measures
and improves through *validated* learning — not a fixed indicator strategy with an AI label. The test for every
component below is: can it change what the bot does only through evidence that survived out-of-sample testing
after realistic costs, and can a deterministic risk engine always veto it?

---

## 0. What exists today and the gaps

The repository already has a sound safety and data foundation. The trading *logic* is the weak part.

| Area | What exists (file) | Gap against the new requirements |
|---|---|---|
| Market data | Read-only MT5 connector, server-time→UTC, tick collector, tick store, M1…D1 + M10 bars, broker bar seeding (`brokers/`, `market/`) | No latency measurement per tick/order; no liquidity proxies beyond spread; tick volume is not labelled as tick volume everywhere; no cross-market symbols (DXY/oil/yields) collected |
| Features / regimes | 15 tick/bar features; regimes trending/ranging/volatile/quiet (`market/features.py`) | Missing breakout, low-liquidity and news-driven regimes; no ADX, VWAP, volume profile or market-structure features; no measurement of which features add information; correlated features (momentum ×3) fed together |
| Entry logic | Two hard-coded candidate generators: momentum continuation and S/R wick rejection (`agents/decision.py`) | This *is* the "fixed strategy with an AI label" problem. No strategy library, no per-strategy evidence, no baselines, no way to retire a setup that loses after costs |
| Model | Online logistic per direction + reliability calibrator (prequential) | Expected value ignores costs (`ev_r = p·RR − (1−p)`); label is `net_pnl > 0` (mixes expiry and trailing exits); no Brier/ECE on out-of-sample; needs 50 trades/direction before signals, so learning relies on exploration trades that lose money by design |
| Testing | Backtest (A), walk-forward (B), live virtual (C), real (D) memories in separate tables; next-tick fills; bid/ask; adverse slippage; stop-first on same tick | Walk-forward folds tune *parameters of the same two setups*; no comparison with simple baselines (random entry with the same bracket, no-trade); no bootstrap uncertainty; no report of failed strategies as a first-class result |
| Risk | Independent veto: 1 position, risk %, daily loss, max DD, spread, stale tick, news blackout, sessions (UTC), min R:R, broker stop level (`risk/engine.py`) | Missing: weekly loss, consecutive-loss limit and cooldown, overtrading cap, margin check, latency filter, abnormal-volatility filter, EV-after-cost gate, observation window, stop-widening prohibition, versioned rule set, Dubai-time sessions |
| Execution | Gated MT5 adapter, reconciliation (orphans/foreign), magic number, order_check, not wired (`execution.py`) | Fine as a base. Needs idempotency keys per decision, ack verification timeout, kill-switch path, restart reconciliation wired into the service before demo execution |
| News | MT5 calendar via EA, classifier, high-impact blackout (`news/`) | No provenance (source, publication / first-seen / ingestion time), no verification or corroboration, no headline feed, no X/Twitter, no cross-market reaction measurement, no "wait / reduce / block" decision record |
| Signals | Single SL/TP, statuses pending/approved/rejected/ignored/manual/expired | Needs entry range, TP1/TP2/TP3, money risk, EV after costs, regime, evidence, invalidation, lifecycle (Waiting, Active, TP1-3, SL, Break-even, Cancelled, Expired), executed/skipped flag, explicit "NO TRADE" |
| Learning control | Self-healing: deterioration tests, candidate params, owner-only promotion, rollback (`agents/self_healing.py`) | Champion/challenger compares parameter tweaks only; no drift detector on feature distributions; no automatic "pause new live entries → back to virtual" state |
| Behaviour | — | No overtrading, loss-chasing or manual-override tracking |
| Time | All UTC | Owner's preferences are in Dubai time (UTC+4, no DST), e.g. 18:00–19:00 Dubai = 14:00–15:00 UTC |

Conclusion: keep the foundation (data, memories, simulator, safety gates, dashboard, deployment) and replace the
decision core with an evidence pipeline: **strategy library → research harness → validated champion → calibrated
EV after costs → deterministic risk veto**.

---

## 1. Architecture and agent responsibilities

"Agent" here means a component with one responsibility, explicit inputs/outputs, and a recorded trail. No agent
can place an order; only the execution gateway can, and only after the risk engine approves and every execution
gate is open. LLMs, where used at all, are limited to *structured extraction* from untrusted text and never
decide trades or risk.

```
           ┌──────────────── Observation ────────────────┐
 MT5 ticks │ Market Data Agent → Market Intelligence Agent│→ features, regime, data-health
 calendar  │ News & Event Agent → Verification Agent      │→ verified events, blackout windows
 X / RSS   │ Cross-Market Agent (DXY, yields, oil, ETF)   │→ measured relationships (hypotheses)
           └──────────────────────┬──────────────────────┘
                                  ▼
           ┌──────────────── Planning ───────────────────┐
           │ Strategy Library (setups, each versioned)    │→ candidate setups with structure stop
           │ Trade Planner (champion strategy + model)    │→ plan: side, entry zone, SL, TP1-3, EV after costs
           │                     or explicit NO TRADE     │
           └──────────────────────┬──────────────────────┘
                                  ▼
           ┌─────────── Independent deterministic risk engine ───────────┐
           │ hard limits, filters, behaviour guard, observation window   │→ APPROVE / BLOCK + reasons
           └──────────────────────┬──────────────────────────────────────┘
                     ┌────────────┴────────────┐
                     ▼                         ▼
          Mode A: Signal Agent         Mode B: Execution Gateway (disabled for real money)
          Telegram/WhatsApp/push       idempotent orders, broker-side SL, ack check, reconciliation
                     └────────────┬────────────┘
                                  ▼
           ┌──────────────── Measurement & learning ─────────────────────┐
           │ Performance Agent (A/B/C/D memories, metrics after costs)    │
           │ Research Agent (offline: strategy & feature evaluation)      │
           │ Champion/Challenger + Drift Agent (promotion needs evidence;  │
           │   owner approves; rollback; degrade → virtual only)          │
           └──────────────────────────────────────────────────────────────┘
```

| Agent | Responsibility | Can it change trading? |
|---|---|---|
| Market Data | Ticks, bars, spread, tick volume (labelled as tick volume), latency, freshness | No; it reports data health that the risk engine reads |
| Market Intelligence | Indicators, market structure, regime labels (trending, ranging, breakout, high-vol, low-liquidity, news-driven) | No; produces inputs |
| News & Event | Calendar, headlines, X posts; records provenance; untrusted text never becomes an instruction | Only through blackout windows and verified-event flags |
| Verification | Dedup, staleness, timestamp sanity, source reliability, impersonation checks, corroboration (≥2 independent reliable sources for material unverified claims), conflicts | Downgrades or blocks; never upgrades a rumour to fact |
| Cross-Market | Rolling relationships of gold with DXY, real yields, oil, equities across windows (1 h, 1 d, 1 w, 1 m); stores them as measurements with uncertainty; causal stories are labelled *hypothesis* | Only as features after validation |
| Strategy Library | Versioned setups (trend pullback, breakout, failed breakout, range mean reversion, liquidity sweep, event-after-stabilisation, plus legacy two) | Only setups promoted by evidence are used live |
| Research | Offline evaluation of setups, features and parameters with chronological splits, baselines, costs, uncertainty; reports failures | Produces candidates only |
| Trade Planner | Champion setup(s) + calibrated model → plan with EV after costs; emits **NO TRADE** with the reason when evidence is insufficient | Proposes; the risk engine disposes |
| Risk Engine | Deterministic veto (§5). Versioned rule set. The planner cannot call around it | Yes — it is the only component that can say yes, and anything can make it say no |
| Behaviour Guard (inside risk) | Overtrading, loss chasing, revenge patterns, repeated manual overrides, cooldowns | Blocks/cools down only |
| Signal | Mode A delivery, lifecycle tracking, executed/skipped record | No |
| Execution Gateway | Mode B; idempotency, broker-side SL, ack verification, reconciliation, kill switch | Executes approved plans only, behind owner gates; real money disabled |
| Performance | Metrics per memory domain after costs | No |
| Champion/Challenger + Drift | Compares challengers on the same data; detects drift and degradation; can only *reduce* activity automatically (pause live entries, return to virtual); promotion needs owner approval | Reduce only |
| Health / Self-healing | Process supervision, data feed checks (existing) | Reduce only |

### Offline learning vs live trading
Offline (research, backtest, walk-forward, learning from closed trades) runs on stored data and needs no broker.
Live decisions — signals and orders — require fresh market data **and** broker connectivity; without them the
system degrades (§6). Learning never runs on an open trade; it updates only after a trade closes (CLAUDE.md rule).

---

## 2. Data sources, licensing, latency and indicative costs

Prices are indicative from public price lists as last known and **must be verified before purchase**; vendors
change tiers often. "Latency" is typical delivery delay to a Windows VPS, not a guarantee.

| Need | Option | Licence / terms | Latency | Indicative cost |
|---|---|---|---|---|
| XAUUSD bid/ask ticks, spread, broker specs | MT5 terminal per broker (Exness, Equiti, MultiBank…) via `MetaTrader5` Python package — **in use** | Broker data for the account holder's own use; not for redistribution | Tens of ms from a VPS near the broker server; measure per broker | Free with a demo/live account |
| Volume | MT5 *tick volume* (number of quote changes) — **not** traded volume | as above | as above | Free. Must be labelled tick volume |
| Centralised gold volume / order book | CME COMEX GC/MGC futures: via a futures broker (CQG, Rithmic, IBKR) or a data vendor (e.g. Databento for CME MDP 3.0) | CME market-data licence; non-professional vs professional status matters | Real-time (ms) | CME non-professional real-time fees are typically low tens of USD/month; vendor usage fees on top; professional much higher. Verify |
| Positioning | CFTC Commitments of Traders (weekly, Tuesday data released Friday) | Public | Days | Free |
| ETF flows | SPDR GLD / iShares IAU daily holdings published by issuers | Public website data; check terms for automated download | Daily | Free |
| Central-bank gold | World Gold Council Goldhub; IMF IFS | Free registration; redistribution limits | Monthly/quarterly | Free |
| Rates / real yields / dollar (daily) | FRED API: DGS10, DFII10 (10y TIPS real yield), DTWEXBGS (broad dollar); US Treasury daily yield curve | Public, attribution | Daily, next business day | Free |
| Intraday DXY / oil / US indices | Broker CFDs where offered (e.g. USDX/DXY, USOIL/UKOIL, US500) discovered like gold | Broker data | Real-time | Free with account; availability varies by broker |
| Economic calendar | MT5 built-in calendar via `GoldAICalendar.mq5` — **in use**. Alternatives: Trading Economics API, Financial Modeling Prep, Finnhub | Vendor terms | Seconds to minutes for actuals | MT5: free. Paid APIs from roughly tens to hundreds of USD/month |
| Official releases | Federal Reserve press-release RSS, FOMC calendar, BLS, BEA, ECB RSS, OPEC press releases, Saudi Press Agency | Public | Seconds–minutes | Free |
| Headlines | Licensed wires (Reuters, Dow Jones/Factiva, Bloomberg) — gold-standard but expensive; mid-tier (Benzinga, Finnhub news, NewsAPI business); GDELT (free, noisy, 15-min) | Vendor licences; most forbid redistribution | Wires: seconds; GDELT: ~15 min | Wires: thousands USD/month; mid-tier: tens–hundreds USD/month; GDELT free |
| X/Twitter | Official X API (tiers have changed repeatedly; filtered streams historically require the higher-priced tiers) or a licensed reseller | X developer agreement; no scraping | Seconds | Historically ~100–200 USD/month for a small read quota, ~5,000 USD/month for Pro streams. Verify current pricing before committing |
| Headline extraction | LLM (e.g. Claude API) used only to extract structured fields (entity, claim, time, source) from untrusted text, never to make decisions | API terms | 1–5 s | Per-token; small at headline volumes |

Recommended start (no new spend): MT5 ticks + MT5 calendar + FRED daily + broker CFDs for DXY/oil if the broker
offers them + official RSS feeds. Add a licensed headline feed and X API only after the event-study research
(§4.4) shows that faster news improves *risk outcomes* (fewer bad fills, smaller tail losses) — not before.
Never claim institutional order flow from spot tick volume.

---

## 3. Database design

Existing tables stay (`mem_a_historical_trades`, `mem_b_forward_trades`, `mem_c_virtual_trades`,
`mem_d_real_trades`, `ticks`, `decisions`, `model_registry`, `runs`, `audit_log`, `kv_state`). Memory D still
accepts only actual broker fills. Nothing is deleted; archival stays an explicit owner action. New tables are
added incrementally with the stage that needs them.

Separation requirement — backtest, forward/virtual and real memories are physically separate tables. The
research harness writes only to Memory A (`runs.kind = 'research'`), walk-forward to Memory B, live virtual to
Memory C, real fills to Memory D.

| Table | Key columns | Stage |
|---|---|---|
| `observations` | id, time, ingested_at, source, kind (tick-gap, spread, latency, cross-market), payload JSON, data_hash | 2 |
| `news_items` | id, source, source_account, url, title, body_hash, published_at, event_time, first_seen_at, ingested_at, language, dedup_key, reliability (0–1), verification (unverified / corroborated / official / refuted / stale / conflicting), corroborated_by [ids], affected_markets, expected_relevance, raw JSON | 3 |
| `event_assessments` | id, news_item_id / calendar_event_id, assessed_at, observed_reaction JSON (gold, DXY, yields, oil returns over 1/5/15/60 min), alternative_explanations [text], uncertainty, action (trade / wait / reduce / block), rule_version | 3 |
| `relationships` | id, computed_at, pair (XAU-DXY, XAU-US10Y-real, XAU-OIL…), window, n, correlation, beta, ci_low, ci_high, regime, label = 'measurement' / 'hypothesis' | 3 |
| `strategy_versions` | version, setup, params JSON, created_at, parent, stage (research / candidate / champion / retired / rejected) | 1 (registry via `runs` + `model_registry`), table in 2 |
| `setup_evaluations` | run_id, setup, split (train / validation / test), trades, expectancy_r, ci_low, ci_high, pf, max_dd, baseline_expectancy_r, verdict, notes | 1 (stored in `runs.metrics`) |
| `decisions` (existing) | + strategy_version, setup, plan JSON, ev_after_cost_r, no_trade_reason | 2 |
| `rejected_setups` | time, setup, side, reason (model / risk / news / data-health), risk_rule_version | 2 (today in `decisions.risk_verdict`) |
| `orders` / `fills` | order_id, idempotency_key (decision id), requested price/volume/SL/TP, sent_at, ack_at, ack_status, latency_ms, fill price, slippage, commission, swap, broker ticket | 4 (execution) |
| `risk_rule_versions` | version (hash of the rule config), config JSON, created_at, actor | 1 |
| `risk_events` | time, rule, verdict, values JSON, mode (virtual / demo / live) | 1 (in `decisions.risk_verdict`), table in 2 |
| `behaviour_events` | time, kind (overtrading / loss-chasing / manual override / cooldown), detail | 2 |
| `signals` (kv today) | + entry_low/high, tp1-3, money_risk, ev_after_cost_r, regime, evidence JSON, invalidation, lifecycle state history, owner_action (executed / skipped / none) | 2 |

---

## 4. Strategy research and validation plan

### 4.1 Principles
- A setup is a *hypothesis*. It earns live use only by positive expectancy **after spread, commission, swap and
  slippage** on data it was not designed or tuned on, and by beating simple baselines on that data.
- Chronological splits only: train (design/tune) → validation (select) → test (score once). Walk-forward repeats
  this across rolling windows. No random shuffles of time series.
- Every evaluated setup is reported, including failures. A failed setup is a useful result.
- Win rate alone is never a criterion. Report expectancy (R and money), profit factor, max drawdown, average R,
  worst trade / 5 % tail, trade count, execution quality (slippage vs estimate), stability across folds and regimes.
- Uncertainty: bootstrap 90 % interval for expectancy in R. A setup whose interval includes 0 is "inconclusive",
  never "profitable".
- Minimum samples: fewer than 30 test trades → "insufficient data". Regime coverage: report per-regime counts; a
  setup tested in one regime only is labelled as such.

### 4.2 Setup library (Stage 1)
Each setup proposes a side and a **structural stop** (beyond the swing / range / sweep extreme, at least
`k·ATR` away), and the trade plan sets TP in R multiples. Indicators are used for distinct roles (trend filter,
location, trigger), not stacked as votes.

| Setup | Role of indicators | Regime it targets |
|---|---|---|
| Trend pullback | EMA(50) slope + ADX(14) ≥ 20 on M15 (trend filter); pullback to EMA(20) on M1/M5 (location); close back in trend direction (trigger) | Trending |
| Breakout | Range of last N M5 bars with Bollinger bandwidth in its lower quantile (compression); M1 close beyond range ± buffer | Breakout |
| Failed breakout | Price pierces the range high/low then closes back inside within K bars | Ranging after false break |
| Range mean reversion | ADX < 20 on M15; close outside Bollinger(20, 2) on M5 then back inside; target VWAP / mid | Ranging |
| Liquidity sweep | Wick beyond a confirmed swing high/low (fractal) and close back inside (market structure) | Any; strongest near session opens |
| Event after stabilisation (Stage 3) | Only after a high-impact release, once spread, ATR and tick rate return within validated bands | News-driven |
| Legacy momentum / S-R rejection | Kept as the incumbent for comparison | — |

Baselines evaluated with the same execution and bracket: (1) **random entry** at the same frequency and side mix
(seeded), (2) **no trade** (0 R), and for context (3) always-long hold over the period. A setup must beat random
entry; otherwise its "edge" is the bracket and the cost model, not the signal.

### 4.3 Indicator evaluation
For each candidate feature (ATR, tick-volume VWAP distance, EMA slopes, ADX, RSI, MACD histogram, Bollinger %B
and bandwidth, volume-profile POC distance, structure distance) compute on the *train* split its information about
the forward outcome of a fixed bracket (triple-barrier label after costs) — rank correlation and AUC — then check
on validation whether the sign and size hold. Pairs with |Spearman ρ| ≥ 0.8 are flagged redundant and only the
more informative one is kept. Features that do not hold out-of-sample are dropped. The result is a short,
uncorrelated feature set for the model, recorded with its run id.

### 4.4 News and cross-market research (Stage 3)
- Event studies on scheduled releases (CPI, NFP, FOMC): spread, ATR, tick rate and returns in windows −30…+120
  min, using the calendar's actual publication and first-seen times. Output: validated no-entry window lengths and
  the "conditions normalised" thresholds that end them.
- Unscheduled events (e.g. an alleged attack on energy infrastructure): verify the event (official / ≥2
  independent reliable sources), timestamp it at first credible report, then measure gold, DXY, yields and oil
  reactions. Record competing explanations (dollar, real yields, inflation expectations, positioning, liquidity).
  No hard-coded "oil up ⇒ gold down" or "war ⇒ gold up": relationships are measured across windows and regimes
  and stored as measurements with intervals, and any causal story is labelled a hypothesis.
- News backtests use only information available at the simulated decision time, including publication delay.

### 4.5 Model and calibration
- The model estimates P(TP before SL) per setup and side from the validated feature set.
- Calibration is checked on out-of-sample predictions (Brier score, expected calibration error, reliability
  bins). Confidence numbers shown to the owner are calibrated hit rates with their sample size, never raw scores.
- EV after costs in R: `EV = p·(RR − c) − (1 − p)·(1 + c)` where `c` = expected round-trip cost / money at risk.
  Proposals with EV below the configured minimum are rejected (risk engine also checks it independently).

### 4.6 Champion / challenger, drift, rollback
- The champion is the setup set + params + model currently used for signals. Challengers run in research and in
  virtual shadow on the same data. A challenger becomes a promotion *candidate* only if it beats the champion out
  of sample with adequate samples and regime coverage over the configured evaluation horizon (1 h, 2 h, 1 d, 2 d,
  1 w — short horizons only flag, they never promote). Promotion needs the owner.
- Drift: population stability of key features and calibration error over recent windows vs the training window.
  On drift or degradation, the system automatically **reduces** activity: pause new live entries, manage open
  positions under their existing stops, return to virtual evaluation. It never automatically increases risk.
- Rollback restores the previous champion by version id (existing self-healing rollback).

---

## 5. Independent risk-engine specification

The risk engine is deterministic code with no learned parameters. Every proposal from every engine passes through
`RiskEngine.evaluate`. It returns APPROVE with a lot size or BLOCK with every failing rule (not just the first)
so blocks can be explained. The rule configuration is hashed into a `risk_rule_version` stored with each verdict.

### 5.1 Hard rules (block)
| # | Rule | Default (illustrative, not a live recommendation) |
|---|---|---|
| R1 | Emergency kill switch active | — |
| R2 | Broker connectivity required; account reconciled after any disconnect/restart before new entries | required |
| R3 | One open trade at a time (per symbol and globally) | 1 |
| R4 | Market data fresh (last tick age) | ≤ 10 s |
| R5 | Spread ≤ limit; spread z-score ≤ limit (abnormal widening) | 60 pts gold; z ≤ 4 |
| R6 | Measured execution latency ≤ limit (when measured) | ≤ 1500 ms |
| R7 | Abnormal volatility: short-term ATR / long ATR ≤ limit | ≤ 3.0 |
| R8 | Max drawdown from peak equity | 10 % |
| R9 | Daily loss limit (resets 00:00 UTC) | 2 % |
| R10 | Weekly loss limit (resets Monday 00:00 UTC) | 4 % |
| R11 | Consecutive losses → cooldown | 3 losses → 60 min |
| R12 | Overtrading: max trades per day; min minutes between entries | 20 / day; 2 min |
| R13 | News no-entry window around high-impact events; resume only after spread/vol/freshness normalise | 15 min before / 15 after |
| R14 | Allowed sessions (configured in UTC and/or Dubai local time) | 24 h; owner preference e.g. 18:00–19:00 Dubai |
| R15 | Startup observation window: virtual only for the first N minutes after start | 5 min |
| R16 | Minimum reward:risk | 1.2 |
| R17 | Minimum EV after costs (R) | > 0.05 R |
| R18 | Calibrated confidence ≥ minimum (exploration only in simulation and labelled) | 0.55 |
| R19 | SL/TP outside broker stop level; symbol tradeable | broker spec |
| R20 | Position size from equity × risk %, stop distance, contract spec; ≤ max lots; ≥ broker min | 0.5 %, 0.10 lot |
| R21 | Margin: required margin ≤ share of free margin (when broker margin is known) | ≤ 30 % |
| R22 | Stop modifications may only reduce risk (never widen a stop) | always |
| R23 | Duplicate prevention: same decision id / same side within the dedup window is rejected | 60 s |

### 5.2 Prohibited everywhere
Martingale, recovery doubling, grid, averaging down, increasing size after losses, forced trades, widening stops to
avoid a loss. Size depends only on equity, stop distance, contract spec and the configured risk % — never on the
previous trade's outcome.

### 5.3 Behaviour control
Detected from measurable inputs: trade frequency vs plan, entries shortly after a loss in the same direction
(loss chasing), repeated manual overrides, rising size after losses (impossible by construction, still checked).
Manual overrides are recorded with actor and reason and can never bypass R1–R23. Cooldowns are explained to the
owner with the rule, the values and when they end. Market "panic/euphoria" is measured, not mind-read: spread
z-score, ATR ratio, tick rate, gap size and headline burst rate.

### 5.4 Execution safeguards (Stage 4, demo first)
Broker-side SL always sent with the order; TP defined; trailing only tightens; idempotency key per decision;
acknowledgment verified within a timeout or the order is reconciled before any retry; reconciliation on start-up
and after reconnect (existing `reconcile`); kill switch closes nothing by itself unless the owner chooses "flatten".

### 5.5 Live risk settings
Account size and risk tolerance have not been given. Every value above is illustrative for research and virtual
trading. Live values will be proposed only after the owner provides account size and risk tolerance, and real
execution stays disabled until explicit owner authorization.

---

## 6. Offline / degraded-operation behaviour

| Condition | Detection | Behaviour |
|---|---|---|
| No broker connection | connector error / no ticks for > 10 s while market open | Block new entries (R2/R4). Virtual positions are managed only on fresh ticks; real positions rely on broker-side SL. On reconnect: reconcile before any entry |
| Stale or contradictory prices | tick age, bid > ask, jump > k·ATR vs last tick, broker vs second source disagreement | Drop bad ticks (existing validation), lower data-health score, block entries until N clean ticks |
| News feed stale | calendar not refreshed within its interval; headline feed silent | Treat the day as "unknown event risk": widen no-entry windows to the configured fallback around known scheduled times, reduce confidence, signal "NO TRADE: news data stale" when inside a likely release window |
| Conflicting news | Verification agent marks conflicting | Block entries for the affected window; record both claims |
| Weekend / closed market | session calendar, no ticks | Offline learning and research only |
| Startup | first N minutes | Observation and virtual only (R15); five minutes is a start-up window, not proof of maturity |
| Performance degradation / drift | §4.6 | Pause new live entries, manage open positions, return to virtual evaluation, notify owner |
| Disk / DB lock / worker crash | health agent, supervisor | Restart with backoff (existing); entries blocked while the decision worker is down |

Offline learning (research, model fitting from closed trades) continues in every condition above. Live decisions
never do.

---

## 7. Staged implementation and acceptance criteria

Every stage ends with tests passing, checkpoint files updated and a commit. "Done" means the acceptance criteria
were met and shown, not that code exists.

### Stage 1 — Evidence engine for XAUUSD scalping (this session)
Deliverables
1. Indicator library: EMA, ADX/DI, Bollinger %B/bandwidth, MACD, RSI (existing), session VWAP on tick volume
   (labelled), tick-volume profile (POC / value area), swing structure and liquidity-sweep detection.
2. Strategy library: trend pullback, breakout, failed breakout, range mean reversion, liquidity sweep, legacy
   incumbent; random-entry baseline. Bar-close decisions, next-tick fills, structural stops.
3. Research harness + CLI `research`: chronological train/validation/test, same simulator and costs as the
   engines, baselines, bootstrap intervals, per-regime counts, verdicts (insufficient_data / rejected /
   inconclusive / candidate), report of every setup including failures, stored in Memory A as `kind=research`.
4. Feature evaluation: information vs triple-barrier outcome after costs, out-of-sample stability, redundancy flags.
5. Risk engine v2: R6, R7, R10, R11, R12, R14 (Dubai time), R15, R17, R21, R22, R23 and a rule version hash;
   EV after costs in the decision agent; explicit "NO TRADE" reasons.

Acceptance
- Unit tests for every indicator against hand-computed values; no indicator reads a bar that has not closed.
- Leakage test: research results on the first part of a series are identical whether or not later data exists.
- Each new risk rule has a test that it blocks and a test that it allows; martingale-style sizing impossible
  (size independent of previous outcomes) is tested.
- `python -m gold_ai research` runs end to end on synthetic data in tests (labelled synthetic) and on the VPS on
  real Equiti ticks; the real-data report is committed **as-is**, including if every setup fails.

Status 2026-10-25: deliverables 1–5 are in the code with 42 new tests (tests/test_research.py,
tests/test_risk_v2.py). Met: no-look-ahead test (a prefix run gives identical closed trades), rule block/allow
tests, sizing independent of past outcomes, end-to-end research on synthetic data. Partly met: EMA, VWAP and
volume profile are checked against hand-computed values; ADX, Bollinger and swings are checked by behaviour
(trend vs chop, bounds, confirmation delay) rather than against a reference table. **Open:** the run on real
Equiti ticks on the VPS. Until that report exists, nothing is known about whether any setup has an edge.

### Stage 2 — Trade planner, signals v2, decision trail
Champion selection from research output; plan with entry range, TP1/TP2/TP3 and break-even rule (simulated with
partial closes), money risk, EV after costs, evidence and invalidation; signal lifecycle (Waiting, Active, TP1,
TP2, TP3, SL, Break-even, Cancelled, Expired) and executed/skipped record; `strategy_versions`,
`risk_rule_versions`, `behaviour_events` tables; dashboard "why no trade" view.
Acceptance: every decision row links strategy version, model version and risk-rule version; lifecycle transitions
tested with tick paths; simulator partial-close P/L reconciles to the cent.

### Stage 3 — News verification and cross-market intelligence
`news_items` with provenance and verification; official RSS + calendar; optional licensed headlines / X API behind
config (no scraping); corroboration and conflict rules; event studies; cross-market relationship measurement from
broker CFDs and FRED; validated no-entry windows and "normalised" thresholds.
Acceptance: injected stale, duplicate, impersonated and conflicting items are downgraded/blocked in tests; news
backtests only see items whose first-seen time ≤ decision time; relationship records carry n and intervals.

### Stage 4 — Validated learning loop
Out-of-sample calibration reporting (Brier, ECE), drift detection, champion/challenger with configurable horizons
and sample/regime requirements, automatic reduce-only actions, owner promotion, rollback.
Acceptance: a simulated degradation pauses live-eligible entries and returns the engine to virtual; promotion is
impossible without owner approval; short horizons cannot promote.

### Stage 5 — Demo execution (owner-enabled demo account only)
Execution gateway wired behind `demo_execution_enabled`, idempotency, ack verification, reconciliation on
restart, kill switch, latency logging.
Acceptance: on a demo account, orders carry broker-side SL, duplicate submissions are rejected, a forced
disconnect/restart reconciles correctly, slippage and latency are recorded per fill.

### Stage 6 — Real money (owner authorization only)
Not scheduled. Requires the owner's account size and risk tolerance, explicit written authorization, a demo track
record reviewed by the owner, and the existing owner grant mechanism. Virtual performance or a maturity score can
never enable it.
