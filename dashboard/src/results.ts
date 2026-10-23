import type { Trade } from "./api";

/** Gold pip convention used in the UI: 1 pip = $0.10 of price. */
export const GOLD_PIP = 0.1;

export function tradePips(t: Trade): number | null {
  if (typeof t.exit_price !== "number" || typeof t.entry_price !== "number") return null;
  const move = String(t.side).toLowerCase() === "buy" ? t.exit_price - t.entry_price : t.entry_price - t.exit_price;
  return move / GOLD_PIP;
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
}

export function periodStats(trades: Trade[]): PeriodStats {
  let wins = 0,
    losses = 0,
    pipsWon = 0,
    pipsLost = 0,
    netPnl = 0;
  for (const t of trades) {
    const p = tradePips(t) ?? 0;
    if (t.net_pnl > 0) wins++;
    else losses++;
    if (p > 0) pipsWon += p;
    else pipsLost += -p;
    netPnl += t.net_pnl;
  }
  return { trades: trades.length, wins, losses, winRate: trades.length ? wins / trades.length : null, pipsWon, pipsLost, netPips: pipsWon - pipsLost, netPnl };
}

/** Closed trades whose exit falls in today / the last 7 days / this calendar month, in the viewer's time zone. */
export function byPeriod(trades: Trade[], now = new Date()): Record<"today" | "week" | "month", Trade[]> {
  const closed = trades.filter((t) => t.exit_time);
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startWeek = startToday - 6 * 86400000;
  const startMonth = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
  const at = (t: Trade) => Date.parse(String(t.exit_time));
  return {
    today: closed.filter((t) => at(t) >= startToday),
    week: closed.filter((t) => at(t) >= startWeek),
    month: closed.filter((t) => at(t) >= startMonth),
  };
}
