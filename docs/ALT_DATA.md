# Alternative data: Quiver Quantitative (optional)

Status: adapter built and tested against mocked HTTP only. **Not verified against the live Quiver API** (no token yet).
It is off unless `quiver_api_token` is set, and it is read-only context for the virtual engine. It does not change
risk, sizing or execution, and real-money trading stays disabled.

## What it pulls
Quiver is equity-focused; only datasets with an indirect link to gold are used. All are daily disclosures, not ticks.

| Feature | Source | No look-ahead rule |
|---|---|---|
| `alt_etf_offex_short_ratio`, `alt_etf_offex_short_z` | off-exchange short volume / total for GLD, IAU (average), z-score vs 60 days | a day's row counts from the next day |
| `alt_congress_gold_net_30d`, `alt_congress_gold_trades_30d` | congress purchases minus sales in GLD, IAU, GDX, NEM over 30 days | by disclosure (report) date, not transaction date |
| `alt_offex_available`, `alt_congress_available` | 1.0 / 0.0 | — |

Without a token, or when a request fails, values are neutral (0.5 ratio, 0 otherwise) with availability 0.
Errors are listed under `source_errors` in `GET /api/altdata`. Data refreshes at start-up and every 6 hours.

These features are shown on `/api/altdata` but are **not yet part of the learned model**: adding them changes the
model's feature schema, which is task T-NEWS-FEATURES (together with news and institutional flags).
No claim is made that this data improves results; that needs recorded virtual trades with and without it.

## Setup (owner, on the VPS)
1. Buy a Quiver API plan at https://api.quiverquant.com/pricing/ (Hobbyist, $30/month, covers both datasets).
2. Add to `config.local.json` (never commit it, never paste the token in chat):
   ```json
   "quiver_api_token": "YOUR_TOKEN",
   "quiver_offexchange_tickers": ["GLD", "IAU"],
   "quiver_congress_tickers": ["GLD", "IAU", "GDX", "NEM"]
   ```
3. Restart the service, then open `/api/altdata`. If `source_errors` shows 404s, Quiver's paths differ from the
   defaults in `gold_ai/altdata/quiver.py` (`QuiverConfig.offexchange_path`, `congress_path`).

## Liquid (liquid.trade)
Not integrated. It is a non-custodial on-chain trading app with no documented developer or market-data API, and it
cannot be an execution venue here (execution is MT5-only and real money is disabled). Revisit only if the owner
confirms the product and it publishes an API.
