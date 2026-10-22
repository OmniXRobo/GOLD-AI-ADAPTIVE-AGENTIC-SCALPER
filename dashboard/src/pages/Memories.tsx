import { useState, type FormEvent, type ReactNode } from "react";
import { api, DOMAINS, DOMAIN_BADGE, DOMAIN_TITLE, type BacktestRequest, type BacktestResult, type Domain, type Metrics, type Run, type WalkForwardReport } from "../api";
import { BrokerBreakdown, Calibration, CostsGrid, DomainPanel, EquityCurve, MetricsGrid, MonthlyChart, RegimeTable, TradesTable, useTrades } from "../components/domain";
import { Card, DataView, DomainBadge, Empty, ErrorState, JsonBlock, PageHeader, Pill, Stat, Table, toneFor } from "../components/ui";
import { fmtMoney, fmtNum, fmtPct, fmtTime, signClass, useApi } from "../lib";
import { useLive } from "../state";
import { VirtualVsReal, useAllDomains } from "./Overview";

// ---------------------------------------------------------------- shared form

interface FormState {
  source: "db" | "synthetic";
  broker: string;
  symbol: string;
  start: string;
  end: string;
  params: string;
}

function RunForm({ onSubmit, busy, extra, submitLabel }: { onSubmit: (r: BacktestRequest) => void; busy: boolean; extra?: ReactNode; submitLabel: string }) {
  const brokers = useApi(api.brokers, []);
  const [f, setF] = useState<FormState>({ source: "db", broker: "", symbol: "XAUUSD", start: "", end: "", params: "" });
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof FormState) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    let params: Record<string, unknown> | undefined;
    if (f.params.trim()) {
      try {
        params = JSON.parse(f.params);
      } catch {
        setErr("Params must be valid JSON");
        return;
      }
    }
    if (!f.broker.trim()) {
      setErr("Broker is required");
      return;
    }
    onSubmit({
      source: f.source,
      broker: f.broker.trim(),
      symbol: f.symbol.trim(),
      start: f.start ? new Date(f.start).toISOString() : undefined,
      end: f.end ? new Date(f.end).toISOString() : undefined,
      params,
    });
  };

  return (
    <form className="form" onSubmit={submit}>
      <label className="field">
        <span>Data source</span>
        <select value={f.source} onChange={set("source")}>
          <option value="db">Recorded ticks (db)</option>
          <option value="synthetic">Synthetic (pipeline test only)</option>
        </select>
      </label>
      <label className="field">
        <span>Broker</span>
        <input list="broker-list" value={f.broker} onChange={set("broker")} placeholder={brokers.data?.length ? "choose a broker" : "broker id"} />
        <datalist id="broker-list">
          {(brokers.data ?? []).map((b) => (
            <option key={b.broker} value={b.broker} />
          ))}
        </datalist>
      </label>
      <label className="field">
        <span>Symbol</span>
        <input value={f.symbol} onChange={set("symbol")} />
      </label>
      <label className="field">
        <span>Start (optional)</span>
        <input type="datetime-local" value={f.start} onChange={set("start")} />
      </label>
      <label className="field">
        <span>End (optional)</span>
        <input type="datetime-local" value={f.end} onChange={set("end")} />
      </label>
      {extra}
      <label className="field field-wide">
        <span>Params override (JSON, optional)</span>
        <textarea rows={3} value={f.params} onChange={set("params")} placeholder='{"min_confidence": 0.6}' className="mono" />
      </label>
      {f.source === "synthetic" && <p className="state state-warn field-wide">Synthetic data validates the pipeline only. Results say nothing about real market edge.</p>}
      {err && <p className="state state-error field-wide">{err}</p>}
      <div className="field-wide">
        <button className="btn btn-primary" disabled={busy}>
          {busy ? "Running..." : submitLabel}
        </button>
      </div>
    </form>
  );
}

function RunsTable({ domain }: { domain: "historical" | "forward" }) {
  const st = useApi(() => api.runs(domain), [domain]);
  return (
    <Card title="Recorded runs" badge={<DomainBadge domain={domain} />} actions={<button className="btn btn-small" onClick={st.reload}>Refresh</button>}>
      <DataView state={st} isEmpty={(r) => !r.length} empty="No runs recorded yet.">
        {(rows) => (
          <Table<Run>
            rows={rows}
            rowKey={(r, i) => r.run_id ?? String(i)}
            columns={[
              { key: "created_at", label: "Created", render: (r) => fmtTime(r.created_at) },
              { key: "kind", label: "Kind" },
              { key: "broker", label: "Broker" },
              { key: "data_source", label: "Data", render: (r) => (r.data_source === "synthetic" ? <Pill tone="warn">synthetic</Pill> : r.data_source ?? "n/a") },
              { key: "period", label: "Period", render: (r) => <span className="small">{fmtTime(r.period_start)} to {fmtTime(r.period_end)}</span> },
              { key: "trades", label: "Trades", className: "num", render: (r) => String(r.metrics?.total_trades ?? "n/a") },
              { key: "wr", label: "Win rate", className: "num", render: (r) => (r.metrics?.total_trades ? fmtPct(r.metrics.win_rate) : "n/a") },
              { key: "net", label: "Net P/L", className: "num", render: (r) => <span className={signClass(r.metrics?.net_profit)}>{fmtMoney(r.metrics?.net_profit)}</span> },
              { key: "model", label: "Model end", render: (r) => <span className="mono small">{r.model_version_end ?? "n/a"}</span> },
              { key: "hash", label: "Data hash", render: (r) => <span className="mono small">{(r.data_hash ?? "").slice(0, 10) || "n/a"}</span> },
            ]}
          />
        )}
      </DataView>
    </Card>
  );
}

// ---------------------------------------------------------------- backtesting

export function BacktestingPage() {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<BacktestResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [key, setKey] = useState(0);
  return (
    <>
      <PageHeader title="Historical Backtesting" subtitle={<>All results here are <strong>{DOMAIN_BADGE.historical}</strong>. Costs (spread, commission, swap, slippage) come from broker metadata.</>} />
      <Card title="Run a backtest" badge={<DomainBadge domain="historical" />}>
        <RunForm
          busy={busy}
          submitLabel="Run backtest"
          onSubmit={async (req) => {
            setBusy(true);
            setErr(null);
            setRes(null);
            try {
              setRes(await api.backtest(req));
              setKey((k) => k + 1);
            } catch (e) {
              setErr((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        />
      </Card>
      {err && <ErrorState error={err} />}
      {res && (
        <Card title={`Result${res.run_id ? ` - run ${res.run_id}` : ""}`} badge={<DomainBadge domain="historical" />}>
          {res.label && <p className="muted small">Backend label: {res.label}</p>}
          {res.metrics ? (
            <>
              <MetricsGrid metrics={res.metrics} domain="historical" />
              <CostsGrid metrics={res.metrics} />
              <div className="grid-2">
                <MonthlyChart monthly={res.metrics.monthly} />
                <RegimeTable byRegime={res.metrics.by_regime} />
              </div>
            </>
          ) : (
            <Empty>Backend returned no metrics for this run.</Empty>
          )}
          {res.trades && <TradesTable trades={res.trades} domain="historical" />}
          <details>
            <summary>Raw response</summary>
            <JsonBlock value={{ ...res, trades: res.trades ? `[${res.trades.length} trades]` : undefined }} />
          </details>
        </Card>
      )}
      <RunsTable key={`h${key}`} domain="historical" />
      <DomainPanel key={`p${key}`} domain="historical" />
    </>
  );
}

// ---------------------------------------------------------------- forward / walk-forward

function FoldMetric({ m }: { m?: Partial<Metrics> }) {
  if (!m || !m.total_trades) return <span className="muted">0 trades</span>;
  return (
    <span className="small">
      {m.total_trades} tr / <span className={signClass(m.net_profit)}>{fmtMoney(m.net_profit)}</span> / exp {fmtMoney(m.expectancy)}
    </span>
  );
}

export function ForwardPage() {
  const [busy, setBusy] = useState(false);
  const [rep, setRep] = useState<WalkForwardReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [days, setDays] = useState({ train: "", validation: "", test: "" });
  const [key, setKey] = useState(0);
  const numOrUndef = (s: string) => (s.trim() === "" ? undefined : Number(s));

  return (
    <>
      <PageHeader
        title="Forward Validation"
        subtitle={
          <>
            Walk-forward analysis on <strong>historical</strong> data (train / validation / out-of-sample test folds). It is <strong>not live forward trading</strong>. Label: {DOMAIN_BADGE.forward}.
          </>
        }
      />
      <Card title="Run walk-forward" badge={<DomainBadge domain="forward" />}>
        <RunForm
          busy={busy}
          submitLabel="Run walk-forward"
          extra={
            <>
              {(["train", "validation", "test"] as const).map((k) => (
                <label className="field" key={k}>
                  <span>{k[0].toUpperCase() + k.slice(1)} days (optional)</span>
                  <input type="number" min={1} value={days[k]} onChange={(e) => setDays({ ...days, [k]: e.target.value })} />
                </label>
              ))}
            </>
          }
          onSubmit={async (req) => {
            setBusy(true);
            setErr(null);
            setRep(null);
            try {
              setRep(await api.walkforward({ ...req, train_days: numOrUndef(days.train), validation_days: numOrUndef(days.validation), test_days: numOrUndef(days.test) }));
              setKey((k) => k + 1);
            } catch (e) {
              setErr((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        />
      </Card>
      {err && <ErrorState error={err} />}
      {rep && (
        <Card title="Walk-forward report" badge={<DomainBadge domain="forward" />}>
          <p className="muted small">{rep.label}</p>
          <div className="stats">
            <Stat label="Verdict" value={<Pill tone={toneFor(rep.verdict)}>{rep.verdict}</Pill>} />
            <Stat label="Selection stability" value={fmtPct(rep.selection_stability)} />
            {rep.oos_trades !== undefined && <Stat label="OOS trades" value={String(rep.oos_trades)} />}
            {rep.oos_net !== undefined && <Stat label="OOS net P/L" value={fmtMoney(rep.oos_net)} tone={signClass(rep.oos_net)} />}
            {rep.oos_expectancy !== undefined && <Stat label="OOS expectancy" value={fmtMoney(rep.oos_expectancy)} />}
          </div>
          <h3>Overfitting flags</h3>
          {rep.overfit_flags?.length ? (
            <ul className="flags">
              {rep.overfit_flags.map((f, i) => (
                <li key={i}>
                  <Pill tone="warn">flag</Pill> {f}
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No overfitting flags raised.</Empty>
          )}
          <h3>Folds</h3>
          <Table
            rows={rep.folds ?? []}
            rowKey={(_, i) => String(i)}
            empty="No folds (period too short?)."
            columns={[
              { key: "i", label: "#", render: (f) => (typeof f.fold === "object" ? String(f.fold?.index ?? "") : String(f.fold ?? "")) },
              { key: "test", label: "Test window", render: (f) => (typeof f.fold === "object" && f.fold?.test ? <span className="small">{fmtTime(f.fold.test[0])} to {fmtTime(f.fold.test[1])}</span> : "n/a") },
              { key: "selected", label: "Selected", render: (f) => <span className="mono small">{f.selected ?? "none"}</span> },
              { key: "train", label: "Train", render: (f) => <FoldMetric m={f.train_metrics} /> },
              { key: "val", label: "Validation", render: (f) => <FoldMetric m={f.validation_metrics} /> },
              { key: "test_m", label: "Test (OOS)", render: (f) => <FoldMetric m={f.test_metrics} /> },
              { key: "notes", label: "Notes", render: (f) => <span className="small">{(f.notes ?? []).join("; ")}</span> },
            ]}
          />
        </Card>
      )}
      <RunsTable key={`f${key}`} domain="forward" />
      <DomainPanel key={`p${key}`} domain="forward" />
    </>
  );
}

// ---------------------------------------------------------------- virtual

export function VirtualPage() {
  const { overview } = useLive();
  const engines = overview?.virtual_engines ?? [];
  const open = engines.reduce<number | null>((a, e) => (typeof e.open_positions === "number" ? (a ?? 0) + e.open_positions : a), null);
  return (
    <>
      <PageHeader title="Live Virtual Trading" subtitle={<>Paper trades on live ticks with estimated fills. Label: {DOMAIN_BADGE.virtual}.</>} />
      <Card title="Engines" badge={<DomainBadge domain="virtual" />}>
        {overview ? (
          <div className="stats">
            <Stat label="Engines running" value={String(engines.length)} />
            <Stat label="Active virtual positions" value={open === null ? "n/a" : String(open)} />
          </div>
        ) : (
          <Empty>Status not received yet.</Empty>
        )}
      </Card>
      <DomainPanel domain="virtual" refreshMs={15000} />
    </>
  );
}

// ---------------------------------------------------------------- real

export function RealPage() {
  const { auth, authError } = useLive();
  return (
    <>
      <PageHeader title="Real Trading" subtitle={<>Executions confirmed by the broker. Label: {DOMAIN_BADGE.real}.</>} />
      <Card title="Authorization state">
        {auth ? (
          <div className="stats">
            <Stat label="Real trading" value={auth.real_trading_enabled ? "ENABLED" : "DISABLED"} tone={auth.real_trading_enabled ? "neg" : ""} />
            <Stat label="Grant expires" value={auth.grant?.expires_at ? fmtTime(auth.grant.expires_at) : "no active grant"} />
            <Stat label="Max lots" value={auth.grant?.max_lots !== undefined ? fmtNum(auth.grant.max_lots, 2) : "n/a"} />
            <Stat label="Allowlisted accounts" value={auth.account_allowlist?.length ? auth.account_allowlist.join(", ") : "none"} />
          </div>
        ) : authError ? (
          <ErrorState error={authError} />
        ) : (
          <div className="state state-loading">Loading...</div>
        )}
      </Card>
      <DomainPanel domain="real" refreshMs={15000} />
    </>
  );
}

// ---------------------------------------------------------------- memory

const MEMORY_TEXT: Record<Domain, string> = {
  historical: "Backtests on recorded (or explicitly synthetic) tick history. Used to generate hypotheses only.",
  forward: "Out-of-sample folds from walk-forward analysis on historical data. Guards against overfitting; still not live.",
  virtual: "Paper trades on the live feed with estimated fills, spread and slippage. No broker order is sent.",
  real: "Orders actually filled by a broker, with broker-reported prices and costs.",
};

export function MemoryPage() {
  const { overview, overviewError } = useLive();
  return (
    <>
      <PageHeader title="AI Memory" subtitle="Four independent memories. They are stored in separate tables and never merged into one statistic." />
      {!overview && overviewError && <ErrorState error={overviewError} />}
      <div className="grid-2">
        {DOMAINS.map((d) => (
          <Card key={d} title={DOMAIN_TITLE[d]} badge={<DomainBadge domain={d} />}>
            <Stat label="Records" value={overview ? overview.memory_counts?.[d]?.toLocaleString() ?? "n/a" : "..."} />
            <p className="small muted">{MEMORY_TEXT[d]}</p>
          </Card>
        ))}
      </div>
    </>
  );
}

// ---------------------------------------------------------------- performance

export function PerformancePage() {
  const [domain, setDomain] = useState<Domain>("virtual");
  const st = useTrades(domain, 200);
  const all = useAllDomains();
  return (
    <>
      <PageHeader
        title="Performance Analytics"
        subtitle="Statistics are always per memory domain."
        actions={
          <div className="seg" role="tablist">
            {DOMAINS.map((d) => (
              <button key={d} role="tab" aria-selected={d === domain} className={`seg-btn ${d === domain ? "active" : ""}`} onClick={() => setDomain(d)}>
                {d}
              </button>
            ))}
          </div>
        }
      />
      <Card title={DOMAIN_TITLE[domain]} badge={<DomainBadge domain={domain} />}>
        <DataView state={st}>
          {(d) => (
            <>
              <MetricsGrid metrics={d.metrics} domain={domain} />
              <CostsGrid metrics={d.metrics} />
              {d.metrics?.total_trades > 0 && (
                <div className="stats compact">
                  {d.metrics.sharpe_per_trade !== undefined && <Stat label="Sharpe / trade" value={d.metrics.sharpe_per_trade === null ? "n/a (<30 trades)" : fmtNum(d.metrics.sharpe_per_trade)} />}
                  {d.metrics.gross_profit !== undefined && <Stat label="Gross profit" value={fmtNum(d.metrics.gross_profit)} />}
                  {d.metrics.gross_loss !== undefined && <Stat label="Gross loss" value={fmtNum(d.metrics.gross_loss)} />}
                </div>
              )}
            </>
          )}
        </DataView>
      </Card>
      <div className="grid-2">
        <Card title="Cumulative net P/L" badge={<DomainBadge domain={domain} />}>
          <DataView state={st}>{(d) => <EquityCurve trades={d.trades} />}</DataView>
        </Card>
        <Card title="Monthly net P/L" badge={<DomainBadge domain={domain} />}>
          <DataView state={st}>{(d) => <MonthlyChart monthly={d.metrics?.monthly} />}</DataView>
        </Card>
        <Card title="By market regime" badge={<DomainBadge domain={domain} />}>
          <DataView state={st}>{(d) => <RegimeTable byRegime={d.metrics?.by_regime} />}</DataView>
        </Card>
        <Card title="Per-broker performance" badge={<DomainBadge domain={domain} />}>
          <DataView state={st}>{(d) => <BrokerBreakdown data={d} />}</DataView>
        </Card>
        <Card title="Exit reasons" badge={<DomainBadge domain={domain} />}>
          <DataView state={st}>
            {(d) => {
              const rows = Object.entries(d.metrics?.exit_reasons ?? {}).map(([reason, n]) => ({ reason, n }));
              return <Table rows={rows} rowKey={(r) => r.reason} empty="No exits yet." columns={[{ key: "reason", label: "Reason" }, { key: "n", label: "Trades", className: "num" }]} />;
            }}
          </DataView>
        </Card>
        <Card title="Confidence calibration" badge={<DomainBadge domain={domain} />}>
          <DataView state={st}>{(d) => <Calibration metrics={d.metrics} />}</DataView>
        </Card>
      </div>
      <Card title="Virtual vs live comparison">
        <VirtualVsReal virtual={all.virtual} real={all.real} />
      </Card>
    </>
  );
}
