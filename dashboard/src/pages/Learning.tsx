import { useState } from "react";
import { api, type MaturityStages, type ModelInfo } from "../api";
import { Card, ConfirmDialog, DataView, Empty, JsonBlock, KVTable, PageHeader, Pill, Stat, Table, toneFor } from "../components/ui";
import { fmtNum, fmtTime, fmtValue, humanize, useApi } from "../lib";

// ---------------------------------------------------------------- maturity

const STAGE_ORDER: (keyof MaturityStages)[] = ["observation_ready", "data_sufficient", "statistically_validated", "operationally_ready", "live_authorized"];

export function MaturityPage() {
  const brokers = useApi(api.brokers, []);
  const [broker, setBroker] = useState("");
  const st = useApi(() => api.maturity(broker || undefined), [broker], 60000);
  return (
    <>
      <PageHeader
        title="AI Maturity"
        subtitle="Evidence gates the agent must pass. A maturity score is informational only: it never enables real trading. Only the owner authorization flow can."
        actions={
          <label className="field inline">
            <span>Broker</span>
            <select value={broker} onChange={(e) => setBroker(e.target.value)}>
              <option value="">All / default</option>
              {(brokers.data ?? []).map((b) => (
                <option key={b.broker} value={b.broker}>
                  {b.broker}
                </option>
              ))}
            </select>
          </label>
        }
      />
      <DataView state={st}>
        {(m) => (
          <>
            <Card title="Score">
              <div className="stats">
                <Stat label="Maturity score" value={m.score === null || m.score === undefined ? "n/a" : fmtNum(m.score, 1)} hint="Does not authorize trading" />
                <Stat label="Gates passed" value={`${(m.gates ?? []).filter((g) => g.passed).length} / ${(m.gates ?? []).length}`} />
              </div>
              {m.explanation && <p>{m.explanation}</p>}
            </Card>
            <Card title="Stages">
              <ol className="stages">
                {STAGE_ORDER.map((k) => {
                  const v = m.stages?.[k];
                  return (
                    <li key={k} className={v ? "done" : ""}>
                      <Pill tone={v === undefined ? "neutral" : v ? "ok" : "neutral"}>{v === undefined ? "not reported" : v ? "reached" : "not reached"}</Pill> {humanize(k)}
                      {k === "live_authorized" && <span className="muted small"> (set only by owner authorization)</span>}
                    </li>
                  );
                })}
              </ol>
            </Card>
            <Card title="Gates">
              <Table
                rows={m.gates ?? []}
                rowKey={(g) => g.name}
                empty="No gates reported."
                columns={[
                  { key: "name", label: "Gate", render: (g) => humanize(g.name) },
                  { key: "passed", label: "Result", render: (g) => <Pill tone={g.passed ? "ok" : "bad"}>{g.passed ? "pass" : "fail"}</Pill> },
                  { key: "observed", label: "Observed", className: "num", render: (g) => fmtValue(g.observed) },
                  { key: "threshold", label: "Threshold", className: "num", render: (g) => fmtValue(g.threshold) },
                ]}
              />
            </Card>
            <div className="grid-2">
              <Card title="Uncertainty">
                <KVTable data={m.uncertainty} emptyText="No uncertainty estimates reported." />
              </Card>
              <Card title="Required tests">
                {m.required_tests?.length ? (
                  <ul>
                    {m.required_tests.map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                ) : (
                  <Empty>No outstanding tests reported.</Empty>
                )}
              </Card>
            </div>
          </>
        )}
      </DataView>
    </>
  );
}

// ---------------------------------------------------------------- strategy versions

export function StrategiesPage() {
  const st = useApi(api.models, []);
  const [act, setAct] = useState<{ kind: "promote" | "rollback"; m: ModelInfo } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Strategy Versions" subtitle="Immutable model registry. Stage changes are audited." actions={<button className="btn" onClick={st.reload}>Refresh</button>} />
      {msg && <p className="state state-ok">{msg}</p>}
      <Card title="Registered models">
        <DataView state={st} isEmpty={(d) => !d.length} empty="No models registered yet.">
          {(rows) => (
            <Table
              rows={[...rows].reverse()}
              rowKey={(m) => m.version}
              columns={[
                { key: "version", label: "Version", render: (m) => <span className="mono">{m.version}</span> },
                { key: "strategy_version", label: "Strategy" },
                { key: "parent", label: "Parent", render: (m) => <span className="mono small">{m.parent ?? "none"}</span> },
                { key: "stage", label: "Stage", render: (m) => <Pill tone={toneFor(m.stage === "approved" ? "ok" : m.stage === "rejected" ? "fail" : "neutral")}>{m.stage}</Pill> },
                { key: "created_at", label: "Created", render: (m) => fmtTime(m.created_at) },
                { key: "notes", label: "Notes", render: (m) => <span className="small">{m.notes ?? ""}</span> },
                {
                  key: "actions",
                  label: "Actions",
                  render: (m) => (
                    <div className="row-actions">
                      <button className="btn btn-small" onClick={() => setAct({ kind: "promote", m })}>
                        Promote
                      </button>
                      <button className="btn btn-small" onClick={() => setAct({ kind: "rollback", m })}>
                        Roll back to
                      </button>
                    </div>
                  ),
                },
              ]}
            />
          )}
        </DataView>
      </Card>
      <ConfirmDialog
        open={act !== null}
        title={act ? `${act.kind === "promote" ? "Promote" : "Roll back to"} ${act.m.version}?` : ""}
        confirmLabel={act?.kind === "promote" ? "Promote" : "Roll back"}
        body={<p>The backend validates the request against its promotion gates and records it in the audit log. Promotion never enables real trading.</p>}
        onConfirm={async () => {
          if (!act) return;
          const r = act.kind === "promote" ? await api.promote(act.m.version) : await api.rollback(act.m.version);
          setMsg(`${act.kind} ${act.m.version}: ${JSON.stringify(r)}`);
          st.reload();
        }}
        onClose={() => setAct(null)}
      />
    </>
  );
}

// ---------------------------------------------------------------- self-healing

export function SelfHealingPage() {
  const st = useApi(api.selfHealing, [], 30000);
  return (
    <>
      <PageHeader title="Self-Healing History" subtitle="Diagnoses of performance degradation and the corrective actions taken." />
      <DataView state={st}>
        {(d) => (
          <>
            <Card title="Current diagnosis">
              {d.current_diagnosis && Object.keys(d.current_diagnosis).length ? <KVTable data={d.current_diagnosis} /> : <Empty>No active diagnosis.</Empty>}
            </Card>
            <Card title="History">
              {d.history?.length ? (
                <div className="timeline">
                  {[...d.history].reverse().map((h, i) => {
                    const { time, action, ...rest } = h as { time?: string; action?: string } & Record<string, unknown>;
                    return (
                      <div key={i} className="timeline-item">
                        <div className="timeline-head">
                          <strong>{action ? humanize(String(action)) : "event"}</strong>
                          <span className="muted small">{fmtTime(time)}</span>
                        </div>
                        <JsonBlock value={rest} />
                      </div>
                    );
                  })}
                </div>
              ) : (
                <Empty>No self-healing events yet.</Empty>
              )}
            </Card>
          </>
        )}
      </DataView>
    </>
  );
}
