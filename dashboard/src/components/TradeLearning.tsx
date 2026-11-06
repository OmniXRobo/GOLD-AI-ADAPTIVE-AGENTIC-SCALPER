import { api, type LearnerReport, type LearnerSummary } from "../api";
import { fmtNum, fmtTime, humanize, useApi } from "../lib";
import { Card, Empty, Pill } from "./ui";

const fmtR = (s: LearnerSummary | null | undefined) =>
  s && s.trades ? `${s.expectancy_r >= 0 ? "+" : ""}${fmtNum(s.expectancy_r, 2)}R over ${s.trades}` : "no trades";

function Report({ r }: { r: LearnerReport }) {
  const informative = (r.context_signals ?? []).filter((c) => c.informative);
  return (
    <div className="timeline-item">
      <div className="timeline-head">
        <strong>
          {r.symbol} · {humanize(r.style)}
        </strong>{" "}
        <Pill tone={r.verdict === "candidate" ? "ok" : r.verdict === "no_change" ? "neutral" : "warn"}>{humanize(r.verdict)}</Pill>
        <span className="muted small"> {fmtTime(r.created_at)}</span>
      </div>
      <table className="table small">
        <tbody>
          <tr>
            <td>Past virtual trades re-read</td>
            <td className="num">
              {r.trades} ({r.trades_with_context ?? 0} with news / market context)
            </td>
          </tr>
          <tr>
            <td>All trades, as taken</td>
            <td className="num">{fmtR(r.all_trades)}</td>
          </tr>
          <tr>
            <td>Later trades, if it had only taken what it approved (current {fmtNum(r.current_threshold, 2)})</td>
            <td className="num">{fmtR(r.holdout_current)}</td>
          </tr>
          {r.chosen_threshold !== null && (
            <tr>
              <td>Same, with the best threshold found earlier ({fmtNum(r.chosen_threshold, 2)})</td>
              <td className="num">{fmtR(r.holdout_chosen)}</td>
            </tr>
          )}
          {r.brier !== null && (
            <tr>
              <td>Forecast error (Brier, lower is better; 0.25 = coin flip)</td>
              <td className="num">{fmtNum(r.brier, 3)}</td>
            </tr>
          )}
        </tbody>
      </table>
      {r.registered_version ? (
        <p className="small">
          Proposed <code>{r.registered_version}</code>. It waits for the owner on the Strategies page, and nothing changed by itself.
        </p>
      ) : (
        r.reasons?.length > 0 && <p className="muted small">No proposal: {r.reasons.join("; ")}.</p>
      )}
      {r.top_features && Object.keys(r.top_features).length > 0 && (
        <p className="muted small">
          What the model leans on most:{" "}
          {Object.entries(r.top_features)
            .map(([side, fs]) => `${side} ${fs.slice(0, 3).map(([f]) => humanize(f)).join(", ")}`)
            .join(" · ")}
        </p>
      )}
      <p className="muted small">
        News and market data that tracked results in both halves of the history:{" "}
        {informative.length ? informative.map((c) => `${humanize(c.field)} (${fmtNum(c.rho_later ?? 0, 2)})`).join(", ") : "none yet"}
      </p>
    </div>
  );
}

/** What the Trade-History Learner found when it last re-read each engine's past virtual trades. */
export function TradeLearningCard() {
  const st = useApi(api.tradeLearning, [], 120000);
  const reports = Object.values(st.data?.latest ?? {});
  return (
    <Card title="Learning from past trades">
      {st.error ? (
        <Empty>Unavailable: {st.error}</Empty>
      ) : !st.data ? (
        <Empty>Loading...</Empty>
      ) : reports.length ? (
        <>
          <div className="timeline">{reports.map((r) => <Report key={r.report_id} r={r} />)}</div>
          <p className="muted small">
            Once a day the AI re-reads every closed virtual trade. It scores each trade only with what it knew before
            that trade, so these numbers are out of sample. Estimated virtual fills, no real money.
          </p>
        </>
      ) : (
        <Empty>The first review runs about 2 hours after the service starts, then once a day.</Empty>
      )}
    </Card>
  );
}
