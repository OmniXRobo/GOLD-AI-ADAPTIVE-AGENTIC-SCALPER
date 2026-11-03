import type { TradesResponse } from "../api";
import { fmtMoney, fmtPct, signClass } from "../lib";

/** The AI's own approved trades apart from exploration trades taken only to learn, so the learning cost is
 * never read as the agent's performance. */
export function ModeSplit({ data }: { data: TradesResponse | null | undefined }) {
  const by = data?.metrics_by_mode;
  if (!by) return null;
  const rows = [
    { label: "AI's own picks", m: by.model_approved },
    { label: "Learning trades (exploration)", m: by.exploration },
  ];
  return (
    <table className="table small">
      <thead>
        <tr>
          <th></th>
          <th className="num">Trades</th>
          <th className="num">Win rate</th>
          <th className="num">Net P/L</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ label, m }) => (
          <tr key={label}>
            <td>{label}</td>
            <td className="num">{m?.total_trades ?? 0}</td>
            <td className="num">{m?.total_trades ? fmtPct(m.win_rate) : "n/a"}</td>
            <td className={`num ${signClass(m?.net_profit)}`}>{m?.total_trades ? fmtMoney(m.net_profit) : "n/a"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
