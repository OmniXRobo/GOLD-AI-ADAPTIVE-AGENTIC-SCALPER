# Root-cause audit: losing live-virtual results

Status: **open**. Started 2026-10-26 after the owner reported the live-virtual results below.
The strategy involved is under investigation and blocked from promotion, execution and signals
(see "Actions taken"). No trade, model or history has been changed or deleted.

## 1. What was reported, and what is verified so far

Owner's dashboard screenshot (virtual, estimated fills):

| Figure | Reported |
|---|---|
| Closed trades | 34 (11 wins, 23 losses) |
| Win rate | 32.4% |
| Pips | +1,011 / −2,002, net −991 |
| Profit factor | ~0.50 |
| Average win / loss | ~91.9 / ~87.0 pips |

**Not yet verified against the database.** The figures are internally consistent (11 × 91.9 ≈ 1,011;
23 × 87.0 ≈ 2,002), but they have to be reproduced from `mem_c_virtual_trades` on the VPS with the new
read-only command:

```
python -m gold_ai --config config.local.json audit-trades --domain virtual
python -m gold_ai --config config.local.json audit-trades --domain virtual --symbol XAUUSD --style scalp
```

It recomputes the headline exactly as the dashboard Results page does (a win is net P/L > 0, pips are the
fill-to-exit move in the instrument's own pips) and breaks the trades down by exploration flag, entry rule,
symbol, style, side, exit reason, regime, Dubai hour and strategy version. It also runs integrity checks for
duplicates, overlapping positions, money-vs-price arithmetic, stops on the wrong side and exits before
entries. The section 4 hypotheses are settled from that report. Until then, this document separates what the
code proves from what still needs the data.

## 2. Summary

1. **These 34 trades were not a tested strategy. They were exploration.** The live-virtual engine runs the
   adaptive agent with `exploration_rate=0.2` (`runtime.py`). Its model counts as immature until it has 50
   closed trades *per direction* (`min_samples`). With 34 trades in total it was immature throughout, so
   every trade it took was a random 20% acceptance of a candidate from two hard-coded rules: momentum
   continuation and support/resistance wick rejection. The online model never filtered a trade. The results
   therefore measure those two rules, unfiltered, against real quotes. *(Confirmed in code. To be confirmed on
   the data with the `by_exploration` table.)*
2. **The two rules had no demonstrated edge before they traded.** In the first real-data research run
   (docs/research, 3.3 M Equiti ticks, 18–23 Oct) both were `insufficient_data`. `legacy_momentum` scored
   −0.51R on test (90% CI −0.91..−0.02, 10 trades). `legacy_rejection` scored +0.91R on test but −0.44R on
   validation, which is unstable. Nothing in the pipeline required evidence before the virtual engine traded
   them.
3. **The exit design explains the payoff. It does not explain the win rate.** With a stop at −1R, trailing
   that starts at +1R with a 0.8R distance, and a target at +1.5R, a driftless random walk gives about a 50%
   win rate and an average win of about 0.99R (reproduced through the real position simulator in
   `tests/test_investigation_audit.py::test_exit_design_gives_coin_flip_wins_of_about_one_r_on_a_random_walk`, no costs), with
   expectancy about 0. The observed payoff (91.9 / 87.0 ≈ 1.06) matches this exit structure. The observed
   32.4% win rate is far below the ~49% break-even at that payoff. Under a binomial model, 11 or fewer wins in
   34 has p ≈ 0.04. The losses therefore come mainly from **entries that did worse than random**, not from
   costs or exits. The likeliest mechanism is that momentum entries chase a move that has already happened
   (hypothesis H1 below).
4. **Costs are not the cause for this engine.** It uses a 1.5 × ATR(M5) stop, about 87 pips. The spread
   (~2.7 pips on Equiti XAUUSD.sd) plus modelled slippage (0.5 pip per side, plus 1 pip on stops) is about
   5 pips, or about 0.05R. Costs were the dominant problem for the tight structural stops of the research
   setups, not here.
5. **Confirmed defects found and fixed in this change** (section 3): the expected-value formula assumed every
   win pays the full 1.5R target; trade records lost the initial stop and MFE/MAE, so exits could not be
   analysed; exploration trades were reported as if they were strategy performance; and the model was
   overwritten in place without a versioned backup.

## 3. The 24 audit items

Legend: **Defect** = confirmed in code · **OK** = checked, no defect found · **Hypothesis** = needs the VPS data ·
**Gap** = missing capability, planned.

| # | Item | Finding | Status |
|---|---|---|---|
| 1 | Decision logic | An immature model (fewer than 50 closed trades per direction) makes every trade an exploration trade of the two candidate rules, accepted at random 20% of the time. Regime is not used to choose between continuation and reversal. | **Defect** (design): trading before any evidence |
| 2 | Trained model or hard-coded rules | Both. The candidates are hard-coded thresholds (`momentum_threshold` 0.3 ATR, `reversion_distance_atr` 0.5, wick bias ±0.2). The online logistic model is trained only on its own closed virtual trades, so with ≤34 samples it is untrained in practice. | **Defect** (same as 1) |
| 3 | Data freshness | The risk engine rejects ticks older than 10 s; the engine ignores ticks that don't advance. The live engine samples the latest quote every 0.25 s, so its tick features (velocity, short volatility) are built on a sub-sampled stream that differs from research, which uses every tick. | OK · **Gap** (feature parity) |
| 4 | Symbol specs | Taken from broker metadata (Equiti XAUUSD.sd: 2 digits, contract 100, tick value 1.0). The audit's `implied_money_per_price_lot` must come out constant at 100 on the VPS. | OK in code · verify |
| 5 | Pip / point | Gold pip = $0.10 = 10 points, the same in `instruments.py`, the dashboard and the audit. In the all-markets view the dashboard adds pips across instruments (BTC pip = $1), so the screenshot could mix symbols. | OK · **Hypothesis H5** (mixed symbols/styles) |
| 6 | Bid/ask | BUY fills at ask and exits on bid; SELL the reverse. Stops and targets trigger on the closing side. Covered by tests. | OK |
| 7 | Spread | The actual spread of each tick is used; ~2.7 pips against a ~87-pip stop. | OK |
| 8 | Commission / swap | Equiti reports 0 commission for XAUUSD.sd. If the account type does charge commission, it is missing. Swap is charged at UTC midnight (an approximation of server rollover); scalps are held ≤1 h. | **Hypothesis** (account commission) |
| 9 | Slippage | Modelled at 0.5 pip per side plus 1 pip on stops, but not yet calibrated against demo fills (none exist yet). Even 5× this is only ~0.25R. | **Gap** (calibrate on demo) |
| 10 | Entry timing | No look-ahead: decide on tick t, fill on t+1. Momentum entries fire after price has moved more than 0.3 ATR over 15 min with positive tick velocity, which means buying extension. | OK · **Hypothesis H1** (late, chasing entries) |
| 11 | Stop loss | 1.5 × ATR(M5) + spread, placed by volatility rather than structure. It can sit inside obvious M15 swing levels. | **Hypothesis H2** |
| 12 | Take profit / expectancy | Planned 1.5R. The expectancy formula assumed every win pays +1.5R, but trailing exits make the average win about 1R, so EV was overstated by up to ~0.5R × p. | **Defect, fixed**: EV uses the realized win/loss size per direction (`Payoff`) |
| 13 | Trailing | Starts at +1R with a 0.8R distance, so it locks in only +0.2R. On a random walk this is EV-neutral, but it caps the payoff near 1R. Whether it truncates real winners needs MFE data, which was not stored. | **Defect, fixed** (MFE/MAE and initial stop now stored) · **Hypothesis H3** |
| 14 | Expiry | A 3,600 s maximum hold, exiting at market. The share of losses that are expiries comes from the VPS report. | **Hypothesis H4** |
| 15 | Frequency / re-entry | Decides every 5 polled ticks; while flat, an entry follows within seconds of any candidate. Re-entry limits (5 min after a loss, a 60 min cooldown after 3 losses, 20 trades per day) only exist since the risk-engine change of 25 Oct. Earlier trades had none. | **Hypothesis H6** (rapid re-entries) |
| 16 | News filter | Blackouts apply only if `news_calendar_files` is configured on the VPS. Without a calendar file, no trade was ever blocked for news. | **Hypothesis** (check VPS config) |
| 17 | Regime detection | Rule-based thresholds (vol_ratio, efficiency). The regime is recorded on each trade but not used to select entries. No uncertainty, never validated against outcomes. | **Gap** (regime agent with uncertainty planned) |
| 18 | Model training / validation | There was no out-of-sample validation before trading. The label is "closed with a net profit". One reliability calibrator is shared by the BUY and SELL models, so each direction's confidence is diluted by the other's outcomes. | **Defect** (validation: by design of the redesign); calibrator sharing: **Defect**, minor, not yet fixed |
| 19 | Memory persistence | Trades are saved to Memory C on close; model, equity and open positions persist across restarts. However, the stored `stop_loss` is the *final* (trailed) stop, so the initial stop was lost; MFE/MAE were not stored; and the model was overwritten in place. | **Defect, fixed**: initial stop, MFE/MAE and trailing flag in the trade context; registry snapshot of the model at every engine start |
| 20 | Look-ahead | Closed bars only, next-tick fills; covered by tests (`test_backtest_fills_on_next_tick`, causal setup tests). | OK |
| 21 | Leakage | Learning happens only after a trade closes; research splits are chronological; feature selection never touches the test split. Self-healing validates perturbations on the last 2 days only, with no purge or embargo, which is an overfitting risk. | OK · **Gap** (purged walk-forward planned) |
| 22 | Duplicates | Trade ids are unique and there is one position per engine. The audit checks for duplicate entries and overlaps on the real rows. | OK in code · verify |
| 23 | Dashboard vs DB | The Results page computes from the same `/api/trades` rows (limit 5,000), so the figures should match `audit-trades` exactly. However, exploration trades were shown as if they were strategy performance. | **Defect, fixed in the API**: `metrics_by_mode` and a per-trade `exploration` flag; dashboard label pending |
| 24 | Pips vs currency | Wins and losses are counted by money, pips by price. A trade can be a money win with negative pips (e.g. swap), or the reverse. Pips use the fill price, so spread and slippage are included. | OK (by definition) · the audit lists sign mismatches |

## 4. Hypotheses to settle with the VPS report

| Id | Hypothesis | Settled by |
|---|---|---|
| H1 | Momentum-continuation entries are late (adverse selection) and cause most of the loss | `by_entry_rule` win rate / avg R; MFE of new trades |
| H2 | ATR stops sit inside M15 structure and get swept | MAE distribution of new trades vs swing levels |
| H3 | Trailing truncates real winners | `mfe_mae.avg_winner_mfe_r` vs `avg_winner_realized_r` (new trades only) |
| H4 | Time exits add losses | `exits.expiry` count and avg R |
| H5 | The screenshot mixes symbols/styles | `by_symbol`, `by_style` vs the screenshot filter |
| H6 | Rapid re-entries after losses cluster the damage | `spacing.reentries_after_loss_within_300s`, `by_local_hour` |

## 5. Actions taken (this change)

- **Investigation flag.** `gold_ai/strategies/investigation.py` opens `family:adaptive-v1` at startup. This
  family covers every `strat-…` version of the adaptive agent and every `heal-…` self-healing variation of
  it. While it is open:
  - Promotion and rollback to any of its models are refused.
  - The MT5 execution adapter refuses its proposals (stage `investigation`), demo included.
  - Its non-exploration signals are withheld.
  - `/api/overview` engine status, `/api/trades` rows and `/api/strategies/investigations` show the flag.

  Virtual (simulation) trading carries on, so evidence keeps accumulating. Only the owner can close the
  investigation (`POST /api/strategies/investigations/close`, with a reason, audited); a closed one is not
  reopened on restart.
- **Versioned backup.** Each live-virtual engine registers its restored model in the insert-only model
  registry at start. Flagged strategies get stage `under_investigation`, which promotion and rollback refuse.
- **Expectancy fix.** `ModelState` keeps a per-direction `Payoff` (realized win and loss sizes in R, shrunk
  toward the planned bracket). Model versions are unchanged until the first update.
- **Trade facts.** New trades store `initial_stop_loss`, `max_favorable_price`, `max_adverse_price` and
  `trailing_active` in their context.
- **Reporting.** `/api/trades` returns `metrics_by_mode` (exploration vs model-approved) and per-trade
  `exploration` / `investigation` fields.
- **`audit-trades` CLI** (read-only), described in section 1.

## 5b. Findings reported from the VPS (2026-10-26, relayed; reports to be committed verbatim)
- `audit-trades` on 226 virtual trades: about 97% came from momentum continuation, which lost about $816; buy
  trades were the worst. This supports H1 (momentum entries chase the move).
- Research round 2 on 12.6 M ticks: no setup profitable after costs; S/R rejection about 0R.
- Action: momentum continuation is switched off in the live-virtual engines (`virtual_entry_rules`, default
  `["rejection"]`); research round 3 tests the setups a timeframe slower (docs/research/README.md).

## 6. What happens next (no live trading in any step)

1. Run `audit-trades` on the VPS and commit its report verbatim under `docs/audit/`, then settle H1–H6.
2. Replace "trade first, learn later" with evidence first. A setup trades virtually as a non-exploration
   strategy only after passing research and walk-forward. Exploration stays labelled and is reported apart.
3. Regime agent with uncertainty (WAIT when unsure); specialist ensemble with a meta-decision agent that
   returns WAIT on disagreement; dynamic exits (structure stops, model-invalidation exit); a per-direction
   calibrator; drift detection and champion/challenger; purged and embargoed walk-forward; the configurable
   evaluation framework. The order is in TASK_QUEUE.json.
