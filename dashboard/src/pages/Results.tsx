import { useMemo, useState } from "react";
import { DOMAIN_TITLE, type Domain, type Trade } from "../api";
import { useTrades } from "../components/domain";
import { Card, DataView, DomainBadge, Empty, PageHeader } from "../components/ui";
import { fmtMoney, fmtNum, fmtTime, humanize, signClass } from "../lib";
import { byPeriod, GOLD_PIP, periodStats, tradePips, type PeriodStats } from "../results";

const PERIODS = [
  ["today", "Today"],
  ["week", "Last 7 days"],
  ["month", "This month"],
] as const;

function PeriodCard({ label, s }: { label: string; s: PeriodStats }) {
  return (
    <div className="result-card">
      <div className="result-head">
        <span>{label}</span>
        <b>{s.winRate === null ? "n/a" : `${Math.round(s.winRate * 100)}%`}</b>
      </div>
      <div className="muted small">
        win rate · {s.wins} won / {s.losses} lost of {s.trades}
      </div>
      <div className="result-pips">
        <span className="pos">+{fmtNum(s.pipsWon, 0)} pips</span>
        <span className="neg">−{fmtNum(s.pipsLost, 0)} pips</span>
      </div>
      <div className="result-net">
        Net <b className={signClass(s.netPips)}>{fmtNum(s.netPips, 0)} pips</b> · <span className={signClass(s.netPnl)}>{fmtMoney(s.netPnl)}</span>
      </div>
    </div>
  );
}

function History({ trades }: { trades: Trade[] }) {
  const rows = [...trades].filter((t) => t.exit_time).sort((a, b) => String(b.exit_time).localeCompare(String(a.exit_time))).slice(0, 50);
  if (!rows.length) return <Empty>No closed trades yet.</Empty>;
  return (
    <div className="hist">
      {rows.map((t) => {
        const p = tradePips(t);
        const side = String(t.side).toUpperCase();
        return (
          <div className="hist-row" key={t.trade_id}>
            <div className="hist-top">
              <span className={`signal-side ${side === "BUY" ? "buy" : "sell"}`}>{side}</span>
              <span className="muted small">{fmtTime(t.entry_time)}</span>
              <b className={`hist-pips ${signClass(p)}`}>{p === null ? "n/a" : `${p > 0 ? "+" : ""}${fmtNum(p, 0)} pips`}</b>
            </div>
            <div className="hist-levels">
              <span>
                Entry <b>{fmtNum(t.entry_price, 2)}</b>
              </span>
              <span>
                SL <b>{fmtNum(t.stop_loss, 2)}</b>
              </span>
              <span>
                TP <b>{fmtNum(t.take_profit, 2)}</b>
              </span>
              <span>
                Exit <b>{fmtNum(t.exit_price, 2)}</b>
              </span>
              <span className="muted">{t.exit_reason ? humanize(String(t.exit_reason)) : ""}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function ResultsPage() {
  const [domain, setDomain] = useState<Domain>("virtual");
  const st = useTrades(domain, 5000, 60000);
  const periods = useMemo(() => (st.data ? byPeriod(st.data.trades) : null), [st.data]);
  return (
    <>
      <PageHeader title="Results" subtitle="Win rate and pips from trades that actually closed. Nothing is estimated or rounded up." />
      <div className="chips">
        {(["virtual", "real"] as Domain[]).map((d) => (
          <button key={d} className={`chip ${domain === d ? "active" : ""}`} onClick={() => setDomain(d)}>
            {d === "virtual" ? "AI virtual trading" : "Real account"}
          </button>
        ))}
      </div>
      <Card title={DOMAIN_TITLE[domain]} badge={<DomainBadge domain={domain} />}>
        <DataView state={st}>
          {() =>
            periods && (
              <div className="result-grid">
                {PERIODS.map(([k, label]) => (
                  <PeriodCard key={k} label={label} s={periodStats(periods[k])} />
                ))}
              </div>
            )
          }
        </DataView>
        <p className="muted small">
          1 pip = ${GOLD_PIP.toFixed(2)} of gold price. Losing trades include break-even and cost-only losses. {domain === "virtual" ? "Virtual fills are estimated from the live price; no real money." : "Real fills from the broker."}
        </p>
      </Card>
      <Card title="Trade history">
        <DataView state={st}>{(d) => <History trades={d.trades} />}</DataView>
      </Card>
    </>
  );
}
