import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, DOMAIN_TITLE, type Domain, type Metrics, type Trade, type TradesResponse } from "../api";
import { finite, fmtMoney, fmtNum, fmtPct, fmtPF, fmtTime, signClass, useApi, type ApiState } from "../lib";
import { Card, DataView, DomainBadge, Empty, Stat, Table, type Column } from "./ui";

/** Core statistic tiles for one memory domain. Shows an explicit empty state when no trades are closed. */
export function MetricsGrid({ metrics, domain }: { metrics: Metrics; domain: Domain }) {
  if (!metrics || !metrics.total_trades) {
    return <Empty>No closed trades yet in {DOMAIN_TITLE[domain]}.</Empty>;
  }
  return (
    <div className="stats">
      <Stat label="Total trades" value={metrics.total_trades.toLocaleString()} />
      <Stat label="Win rate" value={fmtPct(metrics.win_rate)} hint={metrics.winning_trades !== undefined ? `${metrics.winning_trades} W / ${metrics.losing_trades ?? "?"} L` : undefined} />
      <Stat label="Profit factor" value={fmtPF(metrics.profit_factor)} />
      <Stat label="Net P/L" value={fmtMoney(metrics.net_profit)} tone={signClass(metrics.net_profit)} />
      <Stat label="Max drawdown" value={fmtNum(metrics.max_drawdown)} hint={finite(metrics.max_drawdown_pct) !== null ? `${fmtNum(metrics.max_drawdown_pct, 1)}% of peak` : undefined} />
      <Stat label="Average R" value={fmtNum(metrics.avg_r_multiple)} tone={signClass(metrics.avg_r_multiple)} />
      <Stat label="Expectancy / trade" value={fmtMoney(metrics.expectancy)} tone={signClass(metrics.expectancy)} />
      {finite(metrics.active_positions) !== null && <Stat label="Active positions" value={String(metrics.active_positions)} />}
    </div>
  );
}

export function CostsGrid({ metrics }: { metrics: Metrics }) {
  if (!metrics?.total_trades) return null;
  const items: [string, unknown][] = [
    ["Commission", metrics.total_commission],
    ["Swap", metrics.total_swap],
    ["Spread cost", metrics.total_spread_cost],
    ["Slippage cost", metrics.total_slippage_cost],
  ];
  const shown = items.filter(([, v]) => finite(v) !== null);
  if (!shown.length) return null;
  return (
    <div className="stats compact">
      {shown.map(([k, v]) => (
        <Stat key={k} label={k} value={fmtNum(v)} />
      ))}
    </div>
  );
}

const tradeCols = (domain: Domain): Column<Trade>[] => [
  { key: "entry_time", label: "Entry", render: (t) => fmtTime(t.entry_time) },
  { key: "broker", label: "Broker" },
  { key: "side", label: "Side", render: (t) => <span className={`side side-${String(t.side).toLowerCase()}`}>{t.side}</span> },
  { key: "lots", label: "Lots", className: "num", render: (t) => fmtNum(t.lots, 2) },
  { key: "entry_price", label: "Entry px", className: "num", render: (t) => fmtNum(t.entry_price, 2) },
  { key: "exit_price", label: "Exit px", className: "num", render: (t) => (t.exit_time ? fmtNum(t.exit_price, 2) : <span className="pill pill-info">open</span>) },
  { key: "exit_reason", label: "Exit", render: (t) => t.exit_reason ?? "n/a" },
  { key: "net_pnl", label: "Net P/L", className: "num", render: (t) => <span className={signClass(t.net_pnl)}>{fmtMoney(t.net_pnl)}</span> },
  {
    key: "r",
    label: "R",
    className: "num",
    render: (t) => {
      const r = finite(t.r_multiple) ?? (finite(t.initial_risk_money) ? t.net_pnl / (t.initial_risk_money as number) : null);
      return r === null ? "n/a" : fmtNum(r, 2);
    },
  },
  {
    key: "fill",
    label: "Fill",
    render: (t) =>
      domain === "real" ? (t.is_estimated_fill ? <span className="pill pill-warn">estimated</span> : <span className="pill pill-ok">broker</span>) : <span className="pill pill-neutral">simulated</span>,
  },
  { key: "model_version", label: "Model", render: (t) => <span className="mono small">{t.model_version || "n/a"}</span> },
];

export function TradesTable({ trades, domain }: { trades: Trade[]; domain: Domain }) {
  return <Table rows={trades} columns={tradeCols(domain)} rowKey={(t, i) => t.trade_id ?? String(i)} empty={`No trades recorded in ${DOMAIN_TITLE[domain]} yet.`} />;
}

/** Monthly net P/L bars (diverging by sign). */
export function MonthlyChart({ monthly }: { monthly: Record<string, number> | undefined }) {
  const rows = Object.entries(monthly ?? {})
    .filter(([, v]) => finite(v) !== null)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, net]) => ({ month, net }));
  if (!rows.length) return <Empty>No monthly results yet.</Empty>;
  return (
    <div className="chart" role="img" aria-label="Monthly net profit and loss">
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="month" tick={{ fill: "var(--text-2)", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--grid)" }} />
          <YAxis tick={{ fill: "var(--text-2)", fontSize: 11 }} tickLine={false} axisLine={false} width={56} />
          <ReferenceLine y={0} stroke="var(--text-3)" />
          <Tooltip cursor={{ fill: "var(--hover)" }} contentStyle={tooltipStyle} formatter={(v: number) => [fmtMoney(v), "Net P/L"]} />
          <Bar dataKey="net" radius={[4, 4, 0, 0]} maxBarSize={36}>
            {rows.map((r) => (
              <Cell key={r.month} fill={r.net >= 0 ? "var(--series-pos)" : "var(--series-neg)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export const tooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  color: "var(--text)",
  fontSize: 12,
};

/** Cumulative net P/L over the closed trades actually returned by the API. */
export function EquityCurve({ trades }: { trades: Trade[] }) {
  const closed = trades.filter((t) => t.exit_time && finite(t.net_pnl) !== null).sort((a, b) => String(a.exit_time).localeCompare(String(b.exit_time)));
  if (closed.length < 2) return <Empty>Not enough closed trades for a curve.</Empty>;
  let cum = 0;
  const rows = closed.map((t, i) => {
    cum += t.net_pnl;
    return { i: i + 1, time: t.exit_time as string, cum };
  });
  return (
    <div className="chart" role="img" aria-label="Cumulative net P/L">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="i" tick={{ fill: "var(--text-2)", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--grid)" }} />
          <YAxis tick={{ fill: "var(--text-2)", fontSize: 11 }} tickLine={false} axisLine={false} width={56} />
          <ReferenceLine y={0} stroke="var(--text-3)" />
          <Tooltip contentStyle={tooltipStyle} labelFormatter={(_, p) => fmtTime(p?.[0]?.payload?.time)} formatter={(v: number) => [fmtMoney(v), "Cumulative net"]} />
          <Line type="monotone" dataKey="cum" stroke="var(--series-1)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <p className="muted small">Trade # (x) vs cumulative net P/L over the {closed.length} closed trades returned by the API (most recent page only).</p>
    </div>
  );
}

export function RegimeTable({ byRegime }: { byRegime: Metrics["by_regime"] | undefined }) {
  const rows = Object.entries(byRegime ?? {}).map(([regime, s]) => ({ regime, ...s }));
  return (
    <Table
      rows={rows}
      rowKey={(r) => r.regime}
      empty="No per-regime results yet."
      columns={[
        { key: "regime", label: "Regime" },
        { key: "trades", label: "Trades", className: "num" },
        { key: "wins", label: "Win rate", className: "num", render: (r) => (r.trades ? fmtPct(r.wins / r.trades) : "n/a") },
        { key: "net", label: "Net P/L", className: "num", render: (r) => <span className={signClass(r.net)}>{fmtMoney(r.net)}</span> },
      ]}
    />
  );
}

/** Per-broker performance: uses metrics.by_broker when provided, else groups the returned trades. */
export function BrokerBreakdown({ data }: { data: TradesResponse }) {
  const fromApi = data.metrics?.by_broker;
  let rows: { broker: string; trades: number; wins: number | null; net: number }[];
  let note: string;
  if (fromApi && Object.keys(fromApi).length) {
    rows = Object.entries(fromApi).map(([broker, m]) => ({
      broker,
      trades: (m.total_trades ?? m.trades ?? 0) as number,
      wins: finite(m.win_rate) !== null && (m.total_trades ?? m.trades) ? Math.round((m.win_rate as number) * ((m.total_trades ?? m.trades) as number)) : null,
      net: (m.net_profit ?? m.net ?? 0) as number,
    }));
    note = "Source: metrics.by_broker (all trades in domain).";
  } else {
    const g = new Map<string, { trades: number; wins: number; net: number }>();
    for (const t of data.trades) {
      if (!t.exit_time) continue;
      const r = g.get(t.broker) ?? { trades: 0, wins: 0, net: 0 };
      r.trades++;
      r.wins += t.net_pnl > 0 ? 1 : 0;
      r.net += t.net_pnl;
      g.set(t.broker, r);
    }
    rows = [...g.entries()].map(([broker, r]) => ({ broker, ...r }));
    note = `Computed from the ${data.trades.length} most recent trades returned (backend did not provide metrics.by_broker).`;
  }
  return (
    <>
      <Table
        rows={rows}
        rowKey={(r) => r.broker}
        empty="No closed trades per broker yet."
        columns={[
          { key: "broker", label: "Broker" },
          { key: "trades", label: "Closed trades", className: "num" },
          { key: "wins", label: "Win rate", className: "num", render: (r) => (r.wins !== null && r.trades ? fmtPct(r.wins / r.trades) : "n/a") },
          { key: "net", label: "Net P/L", className: "num", render: (r) => <span className={signClass(r.net)}>{fmtMoney(r.net)}</span> },
        ]}
      />
      {rows.length > 0 && <p className="muted small">{note}</p>}
    </>
  );
}

/** Calibration only if the backend provides it; otherwise says so. */
export function Calibration({ metrics }: { metrics: Metrics | undefined }) {
  const c = metrics?.calibration;
  if (!c || (Array.isArray(c) && !c.length) || (!Array.isArray(c) && !Object.keys(c).length)) {
    return <Empty>Confidence calibration not provided by the backend for this domain.</Empty>;
  }
  if (Array.isArray(c)) {
    return (
      <Table
        rows={c}
        rowKey={(r, i) => String(r.bucket ?? i)}
        columns={[
          { key: "bucket", label: "Confidence bucket" },
          { key: "predicted", label: "Predicted win %", className: "num", render: (r) => fmtPct(r.predicted) },
          { key: "observed", label: "Observed win %", className: "num", render: (r) => fmtPct(r.observed) },
          { key: "count", label: "Trades", className: "num" },
        ]}
      />
    );
  }
  return <pre className="json">{JSON.stringify(c, null, 2)}</pre>;
}

export function useTrades(domain: Domain, limit = 200, refreshMs?: number): ApiState<TradesResponse> {
  return useApi(() => api.trades(domain, limit), [domain, limit], refreshMs);
}

/** Full domain panel: label, metrics, costs, monthly chart, regime table, trades. */
export function DomainPanel({ domain, refreshMs, showTrades = true }: { domain: Domain; refreshMs?: number; showTrades?: boolean }) {
  const st = useTrades(domain, 200, refreshMs);
  return (
    <>
      <Card title={DOMAIN_TITLE[domain]} badge={<DomainBadge domain={domain} />}>
        <DataView state={st}>
          {(d) => (
            <>
              {d.label && <p className="muted small">Backend label: {d.label}</p>}
              {domain !== "real" && d.simulated === false && <p className="state state-error">Backend reports simulated=false for a simulated domain - check the API.</p>}
              <MetricsGrid metrics={d.metrics} domain={domain} />
              <CostsGrid metrics={d.metrics} />
            </>
          )}
        </DataView>
      </Card>
      <div className="grid-2">
        <Card title="Monthly net P/L" badge={<DomainBadge domain={domain} />}>
          <DataView state={st}>{(d) => <MonthlyChart monthly={d.metrics?.monthly} />}</DataView>
        </Card>
        <Card title="By market regime" badge={<DomainBadge domain={domain} />}>
          <DataView state={st}>{(d) => <RegimeTable byRegime={d.metrics?.by_regime} />}</DataView>
        </Card>
      </div>
      {showTrades && (
        <Card title="Trades (latest 200)" badge={<DomainBadge domain={domain} />}>
          <DataView state={st}>{(d) => <TradesTable trades={d.trades} domain={domain} />}</DataView>
        </Card>
      )}
    </>
  );
}
