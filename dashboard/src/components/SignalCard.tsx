import type { Signal } from "../api";
import { fmtNum, fmtTime } from "../lib";

export function signalTime(s: Signal): string | undefined {
  return (s.timestamp ?? s.time) as string | undefined;
}

export function latestSignals(list: Signal[] | null, n: number): Signal[] {
  return [...(list ?? [])].sort((a, b) => String(signalTime(b) ?? "").localeCompare(String(signalTime(a) ?? ""))).slice(0, n);
}

/** Dark ticket-style card for one signal, as the backend recorded it. */
export function SignalCard({ s, compact }: { s: Signal; compact?: boolean }) {
  const side = String(s.side ?? "").toUpperCase();
  const lots = s.suggested_lots ?? s.lots;
  return (
    <article className={`signal-card ${compact ? "signal-card-compact" : ""}`}>
      <header>
        <div>
          <div className="signal-sym">{s.symbol ?? "XAUUSD"}</div>
          <div className="signal-time">
            {fmtTime(signalTime(s))}
            {s.broker ? ` · ${s.broker}` : ""}
          </div>
        </div>
        <span className={`signal-side ${side === "BUY" ? "buy" : side === "SELL" ? "sell" : ""}`}>{side || "n/a"}</span>
      </header>
      <div className="signal-levels">
        <div>
          <span>Entry</span>
          <b>{fmtNum(s.entry, 2)}</b>
        </div>
        <div>
          <span>SL</span>
          <b>{fmtNum(s.stop_loss, 2)}</b>
        </div>
        <div>
          <span>TP</span>
          <b>{fmtNum(s.take_profit, 2)}</b>
        </div>
      </div>
      {!compact && (
        <footer>
          <span>Confidence {typeof s.confidence === "number" ? `${Math.round(s.confidence * 100)}%` : "n/a"}</span>
          {typeof s.risk_reward === "number" && <span>R:R {fmtNum(s.risk_reward, 2)}</span>}
          {typeof lots === "number" && <span>{fmtNum(lots, 2)} lots</span>}
          <span className={`signal-status status-${s.status ?? ""}`}>{s.status ?? "n/a"}</span>
        </footer>
      )}
    </article>
  );
}
