import { Link } from "react-router-dom";
import { api, DOMAINS, DOMAIN_TITLE, type Domain, type ModelInfo, type TradesResponse } from "../api";
import { BrokerBreakdown, Calibration, MetricsGrid, useTrades } from "../components/domain";
import { Card, DataView, DomainBadge, Empty, ErrorState, PageHeader, Pill, Stat, Table, toneFor } from "../components/ui";
import { fmtDuration, fmtMoney, fmtNum, fmtPct, fmtPF, fmtTime, signClass, useApi, type ApiState } from "../lib";
import { useLive } from "../state";

export function DomainSummary({ domain, st }: { domain: Domain; st: ApiState<TradesResponse> }) {
  return (
    <Card title={DOMAIN_TITLE[domain]} badge={<DomainBadge domain={domain} />}>
      <DataView state={st}>{(d) => <MetricsGrid metrics={d.metrics} domain={domain} />}</DataView>
    </Card>
  );
}

export function useAllDomains(refreshMs?: number) {
  return {
    historical: useTrades("historical", 200, refreshMs),
    forward: useTrades("forward", 200, refreshMs),
    virtual: useTrades("virtual", 200, refreshMs),
    real: useTrades("real", 200, refreshMs),
  } satisfies Record<Domain, ApiState<TradesResponse>>;
}

/** Side-by-side live virtual vs real broker metrics; never merged. */
export function VirtualVsReal({ virtual, real }: { virtual: ApiState<TradesResponse>; real: ApiState<TradesResponse> }) {
  const rows: { label: string; get: (d: TradesResponse) => string }[] = [
    { label: "Total trades", get: (d) => String(d.metrics?.total_trades ?? "n/a") },
    { label: "Win rate", get: (d) => (d.metrics?.total_trades ? fmtPct(d.metrics.win_rate) : "n/a") },
    { label: "Profit factor", get: (d) => (d.metrics?.total_trades ? fmtPF(d.metrics.profit_factor) : "n/a") },
    { label: "Net P/L", get: (d) => (d.metrics?.total_trades ? fmtMoney(d.metrics.net_profit) : "n/a") },
    { label: "Max drawdown", get: (d) => (d.metrics?.total_trades ? fmtNum(d.metrics.max_drawdown) : "n/a") },
    { label: "Average R", get: (d) => (d.metrics?.total_trades ? fmtNum(d.metrics.avg_r_multiple) : "n/a") },
    { label: "Expectancy", get: (d) => (d.metrics?.total_trades ? fmtMoney(d.metrics.expectancy) : "n/a") },
  ];
  const cell = (st: ApiState<TradesResponse>, f: (d: TradesResponse) => string) => (st.error ? "unavailable" : st.data ? f(st.data) : "...");
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th>
              Live virtual <DomainBadge domain="virtual" />
            </th>
            <th>
              Real <DomainBadge domain="real" />
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <th>{r.label}</th>
              <td className="num">{cell(virtual, r.get)}</td>
              <td className="num">{cell(real, r.get)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">Virtual results use estimated fills; real results are actual broker fills. They are never combined.</p>
    </div>
  );
}

export function currentVersions(models: ModelInfo[]): ModelInfo[] {
  return models.filter((m) => ["approved", "production", "active", "live"].includes(m.stage));
}

/** Latest real tick from the running engine; shows why it is missing instead of a placeholder price. */
function LiveGoldCard() {
  const st = useApi(api.market, [], 3000);
  const m = st.data;
  const lt = m?.last_tick;
  return (
    <Card
      className="card-hero"
      title={m ? `${m.symbol} live` : "Gold live"}
      badge={m ? <Pill tone={m.ready ? "ok" : "warn"}>{m.ready ? "model ready" : "warming up"}</Pill> : undefined}
      actions={
        <Link to="/market" className="small">
          Market detail
        </Link>
      }
    >
      {m && lt ? (
        <>
          <div className="price-big">{fmtNum(lt.bid, 2)}</div>
          <div className="price-sub">
            <span>
              Ask <b>{fmtNum(lt.ask, 2)}</b>
            </span>
            <span>
              Spread <b>{fmtNum(lt.spread, 2)}</b>
            </span>
            <span>
              Regime <b>{m.regime ?? "n/a"}</b>
            </span>
          </div>
          <p className="muted small">
            {m.broker} · last tick {fmtTime(lt.time)}
          </p>
        </>
      ) : st.error ? (
        <Empty>No live price: {st.error}</Empty>
      ) : m ? (
        <Empty>Connected to {m.broker}; waiting for the first tick.</Empty>
      ) : (
        <div className="state state-loading">Loading...</div>
      )}
    </Card>
  );
}

export default function OverviewPage() {
  const { overview, overviewError, overviewAt } = useLive();
  const doms = useAllDomains(60000);
  const models = useApi(api.models, []);
  const health = useApi(api.systemHealth, [], 30000);

  const engines = overview?.virtual_engines ?? [];
  const openPositions = engines.reduce<number | null>((a, e) => (typeof e.open_positions === "number" ? (a ?? 0) + e.open_positions : a), null);

  return (
    <>
      <PageHeader title="Overview" subtitle={overviewAt ? `Status updated ${overviewAt.toLocaleTimeString()}` : "Waiting for status..."} />

      <div className="hero">
        <LiveGoldCard />
        {overview ? (
          <Card title="Platform state">
            <div className="stats">
              <Stat label="Real trading" value={overview.real_trading_enabled ? "ENABLED" : "DISABLED"} tone={overview.real_trading_enabled ? "neg" : ""} />
              <Stat label="Demo execution" value={overview.demo_execution_enabled ? "enabled" : "disabled"} />
              <Stat label="Emergency stop" value={overview.emergency_stop ? "ACTIVE" : "inactive"} tone={overview.emergency_stop ? "neg" : ""} />
              <Stat label="Active virtual positions" value={openPositions === null ? "n/a" : String(openPositions)} hint={`${engines.length} virtual engine(s)`} />
              <Stat
                label="System health"
                value={health.data ? <Pill tone={toneFor(health.data.overall)}>{health.data.overall}</Pill> : health.error ? "unavailable" : "..."}
              />
            </div>
            <h3>Memory records</h3>
            <div className="stats">
              {DOMAINS.map((d) => (
                <Stat key={d} label={DOMAIN_TITLE[d]} value={overview.memory_counts?.[d]?.toLocaleString() ?? "n/a"} hint={<DomainBadge domain={d} />} />
              ))}
            </div>
          </Card>
        ) : (
          <Card title="Platform state">{overviewError ? <ErrorState error={overviewError} /> : <div className="state state-loading">Loading...</div>}</Card>
        )}
      </div>

      <div className="grid-2">
        {DOMAINS.map((d) => (
          <DomainSummary key={d} domain={d} st={doms[d]} />
        ))}
      </div>

      <div className="grid-2">
        <Card title="Virtual vs live comparison">
          <VirtualVsReal virtual={doms.virtual} real={doms.real} />
        </Card>
        <Card title="Virtual engines (learning duration)" badge={<DomainBadge domain="virtual" />}>
          {!overview ? (
            overviewError ? <ErrorState error={overviewError} /> : <div className="state state-loading">Loading...</div>
          ) : (
            <Table
              rows={engines}
              rowKey={(e, i) => `${e.broker}-${e.symbol}-${i}`}
              empty="No virtual engines running."
              columns={[
                { key: "broker", label: "Broker" },
                { key: "symbol", label: "Symbol" },
                { key: "model_version", label: "Model", render: (e) => <span className="mono small">{e.model_version ?? "n/a"}</span> },
                { key: "open_positions", label: "Open", className: "num" },
                { key: "learning_started", label: "Learning for", render: (e) => fmtDuration(e.learning_started) },
                { key: "equity", label: "Virtual equity", className: "num", render: (e) => fmtNum(e.equity) },
              ]}
            />
          )}
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Per-broker performance" badge={<DomainBadge domain="virtual" />}>
          <DataView state={doms.virtual}>{(d) => <BrokerBreakdown data={d} />}</DataView>
        </Card>
        <Card title="Per-broker performance" badge={<DomainBadge domain="real" />}>
          <DataView state={doms.real}>{(d) => <BrokerBreakdown data={d} />}</DataView>
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Strategy / model version">
          <DataView state={models} isEmpty={(m) => !m.length} empty="No models registered yet.">
            {(m) => {
              const cur = currentVersions(m);
              const latest = m[m.length - 1];
              return (
                <div className="stats">
                  {cur.length ? (
                    cur.map((c) => <Stat key={c.version} label={`Current (${c.stage})`} value={<span className="mono">{c.version}</span>} hint={`strategy ${c.strategy_version}`} />)
                  ) : (
                    <Stat label="Approved model" value="none" hint="No model in an approved stage" />
                  )}
                  <Stat label="Latest registered" value={<span className="mono">{latest.version}</span>} hint={`${latest.stage} - ${fmtTime(latest.created_at)}`} />
                  <Stat label="Registered versions" value={String(m.length)} />
                </div>
              );
            }}
          </DataView>
          <p className="small">
            <Link to="/strategies">Manage strategy versions</Link>
          </p>
        </Card>
        <Card title="Confidence calibration" badge={<DomainBadge domain="virtual" />}>
          <DataView state={doms.virtual}>{(d) => <Calibration metrics={d.metrics} />}</DataView>
        </Card>
      </div>

      <Card title="Latest runs">
        {overview ? (
          <Table
            rows={overview.latest_runs ?? []}
            rowKey={(r, i) => r.run_id ?? String(i)}
            empty="No runs recorded yet."
            columns={[
              { key: "created_at", label: "Created", render: (r) => fmtTime(r.created_at) },
              { key: "domain", label: "Label", render: (r) => (r.domain === "historical" || r.domain === "forward" ? <DomainBadge domain={r.domain} /> : String(r.domain)) },
              { key: "kind", label: "Kind" },
              { key: "broker", label: "Broker" },
              { key: "data_source", label: "Data" },
              { key: "trades", label: "Trades", className: "num", render: (r) => String(r.metrics?.total_trades ?? "n/a") },
              { key: "net", label: "Net P/L", className: "num", render: (r) => <span className={signClass(r.metrics?.net_profit)}>{fmtMoney(r.metrics?.net_profit)}</span> },
            ]}
          />
        ) : (
          <Empty>{overviewError ? "Endpoint unavailable" : "Loading..."}</Empty>
        )}
      </Card>
    </>
  );
}
