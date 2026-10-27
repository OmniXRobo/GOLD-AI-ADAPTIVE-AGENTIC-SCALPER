import { useState } from "react";
import { api, type AgentRow } from "../api";
import { Card, DataView, DomainBadge, PageHeader, Pill } from "../components/ui";
import { fmtMoney, fmtNum, fmtTime, signClass, useApi } from "../lib";

const pf = (r: AgentRow) => (r.trades === 0 ? "n/a" : r.no_losses ? "no losses" : fmtNum(r.profit_factor, 2));

function AgentCell({ r }: { r: AgentRow }) {
  return (
    <div className="agent-cell">
      <b>{r.agent}</b>
      <span className="mono small muted" title="Strategy version">
        {r.version || "n/a"}
      </span>
      {r.model_version && (
        <span className="mono small muted" title="Learning model version">
          {r.model_version}
        </span>
      )}
      <span className="agent-tags">
        {r.running && <Pill tone="ok">running</Pill>}
        {r.champion && <Pill tone="warn">champion</Pill>}
        <span className="muted small">{r.symbols.join(", ")}</span>
      </span>
    </div>
  );
}

export default function AgentsPage() {
  const [domain, setDomain] = useState<"virtual" | "real">("virtual");
  const st = useApi(() => api.agentsBoard(domain), [domain], 60000);
  return (
    <>
      <PageHeader title="AI agents" subtitle="Every AI agent and research lane by name and version, with its total results from closed trades." />
      <div className="seg">
        {(["virtual", "real"] as const).map((d) => (
          <button key={d} className={`seg-btn ${domain === d ? "active" : ""}`} onClick={() => setDomain(d)}>
            {d === "virtual" ? "AI virtual trading" : "Real account"}
          </button>
        ))}
      </div>
      <Card title={domain === "virtual" ? "Totals per agent · virtual" : "Totals per agent · real account"} badge={<DomainBadge domain={domain} />}>
        <DataView state={st} isEmpty={(d) => !d.agents.length} empty={domain === "real" ? "No real trades recorded. Real trading is disabled." : "No agent is running and no trade has closed yet."}>
          {(d) => (
            <div className="table-wrap">
              <table className="agents-table">
                <thead>
                  <tr>
                    <th className="sticky-col">Agent · version</th>
                    <th className="num">Trades</th>
                    <th className="num">Won / lost</th>
                    <th className="num">Win rate</th>
                    <th className="num">Net P/L</th>
                    <th className="num">Profit factor</th>
                    <th className="num">Max drawdown</th>
                    <th className="num">Avg R</th>
                    <th>Last trade</th>
                  </tr>
                </thead>
                <tbody>
                  {d.agents.map((r) => (
                    <tr key={`${r.style}:${r.version}`}>
                      <td className="sticky-col">
                        <AgentCell r={r} />
                      </td>
                      <td className="num">{r.trades}</td>
                      <td className="num">
                        <span className="pos">{r.wins}</span> / <span className="neg">{r.losses}</span>
                      </td>
                      <td className="num">{r.win_rate === null ? "n/a" : `${Math.round(r.win_rate * 100)}%`}</td>
                      <td className={`num ${signClass(r.net_profit)}`}>{r.trades ? fmtMoney(r.net_profit) : "n/a"}</td>
                      <td className="num">{pf(r)}</td>
                      <td className="num">{r.trades ? fmtNum(r.max_drawdown, 2) : "n/a"}</td>
                      <td className={`num ${signClass(r.avg_r)}`}>{r.avg_r === null ? "n/a" : `${r.avg_r > 0 ? "+" : ""}${fmtNum(r.avg_r, 2)}R`}</td>
                      <td className="small">{r.last_trade ? fmtTime(r.last_trade) : "none yet"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataView>
        <p className="muted small">
          A trade counts as won only if it made money after costs. Net P/L and drawdown are in account currency.{" "}
          {domain === "virtual" ? "Virtual fills are estimated from live prices; no real money." : "Real fills from the broker."} The version changes when an agent's rules change, so
          each version keeps its own totals. Swipe the table sideways on a phone.
        </p>
      </Card>
    </>
  );
}
