import type { Trade } from "./api";
import { pipSize } from "./instruments";

/** Gold pip convention used in the UI: 1 pip = $0.10 of price. */
export const GOLD_PIP = 0.1;

/** Pips gained or lost, in the trade's own instrument (gold $0.10, BTC $1, forex 0.0001, JPY pairs 0.01). */
export function tradePips(t: Trade): number | null {
  if (typeof t.exit_price !== "number" || typeof t.entry_price !== "number") return null;
  const pip = (typeof t.pip_size === "number" && t.pip_size > 0 ? t.pip_size : null) ?? pipSize(t.symbol) ?? GOLD_PIP;
  const move = String(t.side).toLowerCase() === "buy" ? t.exit_price - t.entry_price : t.entry_price - t.exit_price;
  return move / pip;
}

export interface PeriodStats {
  trades: number;
  wins: number;
  losses: number;
  winRate: number | null;
  pipsWon: number;
  pipsLost: number;
  netPips: number;
  netPnl: number;
  /** Closed within 1 pip of the entry price. */
  breakeven: number;
  over30: number;
  over50: number;
}

export function periodStats(trades: Trade[]): PeriodStats {
  let wins = 0,
    losses = 0,
    pipsWon = 0,
    pipsLost = 0,
    netPnl = 0,
    breakeven = 0,
    over30 = 0,
    over50 = 0;
  for (const t of trades) {
    const p = tradePips(t) ?? 0;
    if (Math.abs(p) < 1) breakeven++;
    if (p > 30) over30++;
    if (p > 50) over50++;
    if (t.net_pnl > 0) wins++;
    else losses++;
    if (p > 0) pipsWon += p;
    else pipsLost += -p;
    netPnl += t.net_pnl;
  }
  return { trades: trades.length, wins, losses, winRate: trades.length ? wins / trades.length : null, pipsWon, pipsLost, netPips: pipsWon - pipsLost, netPnl, breakeven, over30, over50 };
}

export type Period = "today" | "yesterday" | "week" | "month" | "all";

export const PERIODS: [Period, string][] = [
  ["today", "Today"],
  ["yesterday", "Yesterday"],
  ["week", "Last 7 days"],
  ["month", "This month"],
  ["all", "All"],
];

/** Closed trades whose exit falls in the period, in the viewer's time zone. */
export function inPeriod(trades: Trade[], period: Period, now = new Date()): Trade[] {
  const closed = trades.filter((t) => t.exit_time);
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const at = (t: Trade) => Date.parse(String(t.exit_time));
  switch (period) {
    case "today":
      return closed.filter((t) => at(t) >= startToday);
    case "yesterday":
      return closed.filter((t) => at(t) >= startToday - 86400000 && at(t) < startToday);
    case "week":
      return closed.filter((t) => at(t) >= startToday - 6 * 86400000);
    case "month":
      return closed.filter((t) => at(t) >= new Date(now.getFullYear(), now.getMonth(), 1).getTime());
    default:
      return closed;
  }
}

/** How long a trade was open, e.g. "44m" or "3h 05m". */
export function holdTime(t: Trade): string | null {
  if (!t.exit_time) return null;
  const mins = Math.round((Date.parse(String(t.exit_time)) - Date.parse(t.entry_time)) / 60000);
  if (!Number.isFinite(mins) || mins < 0) return null;
  return mins < 60 ? `${mins}m` : `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, "0")}m`;
}
