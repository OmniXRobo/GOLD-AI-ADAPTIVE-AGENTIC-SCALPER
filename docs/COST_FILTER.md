# Cost-to-risk filter and demo-account mirror (2026-11-25)

## Evidence (virtual trades, Memory C, live engines only, 2026-10-01 .. 2026-11-25)
Recorded cost = spread + commission + entry slippage; risk = money between entry and initial stop.
Average net R per trade, trades whose cost was below the threshold:

| cost/risk < | period          | gold        | BTC        | forex      |
|-------------|-----------------|-------------|------------|------------|
| 10%         | Oct 1 - Nov 7   | 133, +0.11R | 73, +0.38R | 22, +0.83R |
| 10%         | Nov 8 - Nov 25  | 50, +0.02R  | 16, +0.99R | 43, +0.40R |
| 15%         | Oct 1 - Nov 7   | 164, 0.00R  | 126, +0.27R| 70, +0.27R |
| 15%         | Nov 8 - Nov 25  | 56, -0.10R  | 18, +0.92R | 83, +0.19R |

All trades above 10% lost on average (forex >= 30%: 379 trades, -0.91R). The filter is applied to the estimated
round-trip cost before entry (`risk.max_cost_to_risk_pct`, default 12% on the estimate, which adds exit slippage,
~10% on recorded costs). It is a selection on past virtual trades, not a forward result: watch it on new trades.
It removes about three quarters of entries. Exploration trades are exempt.

## Demo mirror (`gold_ai/demo_mirror.py`)
`demo_execution_enabled` + `demo_execution_symbols` (VPS: XAUUSD, BTCUSD) copy each non-exploratory virtual entry
to the MT5 demo account at `demo_execution_lots` (0.01) through `MT5ExecutionAdapter` (refuses real accounts).
Own magic per style (20260502 scalp, 20260512 swing); trailing stops follow; virtual exits close the demo position;
broker results (profit + commission + swap) go to kv `demo_execution_log`; `GET /api/demo` and `/api/overview`
report them. A stop that would risk more than `demo_execution_max_risk_pct` (1.5%) of demo equity at 0.01 is refused.

## Update 2026-11-25 (afternoon)
Almost every virtual entry was an exploration trade (the adaptive model has not passed its confidence gate yet),
and the filter first exempted exploration, so it would have changed nothing. It now applies to every entry.
Oct 1 - Nov 25, exploration trades with cost < 10% of risk: gold scalp 122 trades +0.09R, BTC scalp 61 +0.74R,
forex scalp 36 +0.69R, forex swing 29 +0.36R, BTC swing 26 -0.15R, gold swing 18 -0.21R. The demo mirror now
copies exploration entries too (`demo_execution_include_exploration`) and the VPS mirrors the scalp style only.
