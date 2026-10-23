/** Plain-language copy shared by the Learn page and the public landing page. */
import { GOLD_PIP } from "./results";

export const HOW = [
  ["Read the market", "Open Analysis. Technical shows the trend, momentum and nearby levels from live candles; Fundamental and Calendar show the news that can move gold."],
  ["Watch the AI", "The AI trades a virtual account on the live price around the clock, learns from every closed trade and keeps each memory (backtest, walk-forward, virtual, real) separate."],
  ["Get a signal", "When every check passes (risk limits, spread, news window, confidence), the AI sends a signal with entry, stop loss and take profit to the dashboard, the phone app and Telegram."],
  ["Decide", "You approve, reject or ignore it. Signals never place a real trade by themselves; real-money trading stays locked until the owner grants it."],
  ["Check results", "Results shows win rate and pips by day, week and month from trades that actually closed. Practice lets you try your own trades with practice money."],
];

export const MONEY = [
  ["Risk a small, fixed share", "Risk 0.5–1% of the balance per trade. Ten losses in a row then cost about 10%, not the account."],
  ["Size from the stop, not the target", "Pick the stop loss where the idea is wrong, then let the calculator size the lot. Never widen a stop to fit a bigger lot."],
  ["Daily loss limit", "Stop for the day after a set loss (the risk engine uses a daily cap). Revenge trading is how small losses become big ones."],
  ["No averaging down", "No martingale, grid or adding to losers. The AI's risk engine forbids them, and so should you."],
  ["Mind the news", "Spreads widen and price jumps around high-impact US data. The AI pauses entries around those windows."],
  ["Costs are real", "Spread, commission, swap and slippage are part of every trade. Results here include them."],
];

export const FAQ = [
  ["Does the app trade real money?", "No. Real-money trading is disabled and can only be enabled by the owner with a time-limited, password-confirmed grant. Signals and virtual trading never touch a real account."],
  ["Where do the results come from?", "Only from trades that closed in the AI's virtual account (estimated fills on the live price) or, if ever enabled, real broker fills. Nothing is typed in or estimated after the fact."],
  ["What is a pip on gold?", `This app uses 1 pip = $${GOLD_PIP.toFixed(2)} of price. With 100 oz per lot, 1 pip is worth $10 per 1.00 lot or $0.10 per 0.01 lot.`],
  ["Why didn't I get a signal today?", "The AI only signals when its checks pass. Quiet or news-heavy markets, wide spreads or low confidence mean no trade, which is a decision too."],
  ["How do I get alerts on my phone?", "Install the Android app, sign in, and allow notifications. Alerts are read-only; you act on them in the app."],
  ["Is my practice account linked to the AI?", "No. Practice trades stay in your browser or phone and never enter the AI's memory or a broker."],
];
