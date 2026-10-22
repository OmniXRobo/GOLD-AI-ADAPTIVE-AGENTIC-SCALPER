import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type MarketState } from "../api";
import { RegimeTable, tooltipStyle, useTrades } from "../components/domain";
import { Card, DataView, DomainBadge, Empty, ErrorState, JsonBlock, KVTable, PageHeader, Pill, Stat, Table, toneFor } from "../components/ui";
import { fmtDuration, fmtNum, fmtTime, fmtValue, humanize, useApi } from "../lib";
import { useLive } from "../state";

// ---------------------------------------------------------------- brokers

export function BrokersPage() {
  const st = useApi(api.brokers, [], 10000);
  return (
    <>
      <PageHeader title="Broker Connections" subtitle="MT5 terminals reported by the backend. Refreshes every 10 s." actions={<button className="btn" onClick={st.reload}>Refresh</button>} />
      <Card title="Connections">
        <DataView state={st} isEmpty={(d) => !d.length} empty="No brokers configured.">
          {(rows) => {
            const extra = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((k) => !["broker", "symbol", "connected", "account", "trade_mode", "spread", "latency_ms"].includes(k));
            return (
              <Table
                rows={rows}
                rowKey={(r, i) => `${r.broker}-${i}`}
                columns={[
                  { key: "broker", label: "Broker" },
                  { key: "symbol", label: "Symbol" },
                  { key: "connected", label: "Status", render: (r) => <Pill tone={r.connected ? "ok" : "bad"}>{r.connected ? "connected" : "disconnected"}</Pill> },
                  { key: "account", label: "Account", render: (r) => <span className="mono">{fmtValue(r.account)}</span> },
                  { key: "trade_mode", label: "Trade mode" },
                  { key: "spread", label: "Spread", className: "num", render: (r) => fmtNum(r.spread, 2) },
                  { key: "latency_ms", label: "Latency ms", className: "num", render: (r) => fmtNum(r.latency_ms, 0) },
                  ...extra.map((k) => ({ key: k, label: humanize(k) })),
                ]}
              />
            );
          }}
        </DataView>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- market

interface TickPoint {
  t: string;
  bid: number;
  ask: number;
}

export function MarketPage() {
  const st = useApi(api.market, [], 2000);
  const [ticks, setTicks] = useState<TickPoint[]>([]);
  const lt = st.data?.last_tick;
  useEffect(() => {
    if (!lt || typeof lt.bid !== "number") return;
    setTicks((prev) => (prev.length && prev[prev.length - 1].t === lt.time ? prev : [...prev.slice(-299), { t: lt.time, bid: lt.bid, ask: lt.ask }]));
  }, [lt?.time, lt?.bid, lt?.ask]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <PageHeader title="Gold Live Market" subtitle="XAUUSD state from /api/market/state, polled every 2 s." />
      <DataView state={st}>
        {(m) => (
          <>
            <Card title={`${m.symbol} @ ${m.broker}`} badge={<Pill tone={m.ready ? "ok" : "warn"}>{m.ready ? "ready" : "warming up"}</Pill>}>
              {m.last_tick ? (
                <div className="stats">
                  <Stat label="Bid" value={fmtNum(m.last_tick.bid, 2)} />
                  <Stat label="Ask" value={fmtNum(m.last_tick.ask, 2)} />
                  <Stat label="Spread" value={fmtNum(m.last_tick.spread, 2)} />
                  <Stat label="Last tick" value={fmtTime(m.last_tick.time)} />
                  <Stat label="Regime" value={m.regime ?? "n/a"} />
                </div>
              ) : (
                <Empty>No tick received yet.</Empty>
              )}
            </Card>
            <Card title="Ticks observed in this browser session">
              {ticks.length < 2 ? (
                <Empty>Collecting ticks... ({ticks.length} so far). Only ticks returned by the API are plotted.</Empty>
              ) : (
                <div className="chart" role="img" aria-label="Bid and ask over time">
                  <ResponsiveContainer width="100%" height={240}>
                    <LineChart data={ticks} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid vertical={false} stroke="var(--grid)" />
                      <XAxis dataKey="t" tickFormatter={(v: string) => new Date(v).toLocaleTimeString()} tick={{ fill: "var(--text-2)", fontSize: 11 }} tickLine={false} minTickGap={40} />
                      <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--text-2)", fontSize: 11 }} tickLine={false} axisLine={false} width={64} />
                      <Tooltip contentStyle={tooltipStyle} labelFormatter={(v) => fmtTime(String(v))} formatter={(v: number, n: string) => [fmtNum(v, 2), n]} />
                      <Line type="linear" dataKey="bid" name="Bid" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
                      <Line type="linear" dataKey="ask" name="Ask" stroke="var(--series-2)" strokeWidth={2} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                  <div className="legend">
                    <span>
                      <i style={{ background: "var(--series-1)" }} /> Bid
                    </span>
                    <span>
                      <i style={{ background: "var(--series-2)" }} /> Ask
                    </span>
                  </div>
                </div>
              )}
            </Card>
            <Card title="Feature vector">
              <FeatureTable m={m} />
            </Card>
          </>
        )}
      </DataView>
    </>
  );
}

function FeatureTable({ m }: { m: MarketState }) {
  const rows = Object.entries(m.features ?? {}).map(([name, value]) => ({ name, value }));
  return (
    <Table
      rows={rows}
      rowKey={(r) => r.name}
      empty="No features computed yet (agent may still be warming up)."
      columns={[
        { key: "name", label: "Feature", render: (r) => <span className="mono">{r.name}</span> },
        { key: "value", label: "Value", className: "num", render: (r) => fmtNum(r.value, 4) },
      ]}
    />
  );
}

// ---------------------------------------------------------------- agent

export function AgentPage() {
  const { overview, overviewError } = useLive();
  const signals = useApi(api.signals, [], 15000);
  const engines = overview?.virtual_engines ?? [];
  return (
    <>
      <PageHeader title="AI Agent Status" subtitle="Live virtual engines reported in the status stream." />
      {!overview && overviewError && <ErrorState error={overviewError} />}
      {overview && (
        <Card title="Execution permissions">
          <div className="stats">
            <Stat label="Real trading" value={overview.real_trading_enabled ? "ENABLED" : "DISABLED"} tone={overview.real_trading_enabled ? "neg" : ""} />
            <Stat label="Demo execution" value={overview.demo_execution_enabled ? "enabled" : "disabled"} />
            <Stat label="Emergency stop" value={overview.emergency_stop ? "ACTIVE" : "inactive"} tone={overview.emergency_stop ? "neg" : ""} />
          </div>
        </Card>
      )}
      {overview && !engines.length && <Empty>No virtual engines are running.</Empty>}
      <div className="grid-2">
        {engines.map((e, i) => (
          <Card key={`${e.broker}-${i}`} title={`${e.broker} / ${e.symbol}`} badge={<DomainBadge domain="virtual" />}>
            <div className="stats compact">
              <Stat label="Model" value={<span className="mono small">{e.model_version ?? "n/a"}</span>} />
              <Stat label="Open positions" value={fmtValue(e.open_positions)} />
              <Stat label="Ticks processed" value={fmtValue(e.ticks_processed)} />
              <Stat label="Decisions" value={fmtValue(e.decisions)} />
              <Stat label="Virtual equity" value={fmtNum(e.equity)} />
              <Stat label="Learning for" value={fmtDuration(e.learning_started)} hint={e.learning_started ? `since ${fmtTime(e.learning_started)}` : undefined} />
              <Stat label="Last tick" value={fmtTime(e.last_tick)} />
              <Stat label="Fills" value={e.fills ?? "n/a"} />
            </div>
          </Card>
        ))}
      </div>
      <Card title="Most recent signals">
        <DataView state={signals} isEmpty={(s) => !s.length} empty="No signals yet.">
          {(s) => (
            <Table
              rows={s.slice(0, 10)}
              rowKey={(r, i) => String(r.id ?? i)}
              columns={[
                { key: "time", label: "Time", render: (r) => fmtTime(r.time) },
                { key: "broker", label: "Broker" },
                { key: "side", label: "Side" },
                { key: "confidence", label: "Confidence", className: "num", render: (r) => fmtNum(r.confidence, 2) },
                { key: "status", label: "Status" },
                { key: "explanation", label: "Explanation", render: (r) => <span className="small">{r.explanation ?? ""}</span> },
              ]}
            />
          )}
        </DataView>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- market intelligence

export function IntelligencePage() {
  const market = useApi(api.market, [], 5000);
  const virt = useTrades("virtual");
  const hist = useTrades("historical");
  return (
    <>
      <PageHeader title="Market Intelligence" subtitle="Current regime classification and how each regime has performed per memory." />
      <Card title="Current regime">
        <DataView state={market}>
          {(m) => (
            <div className="stats">
              <Stat label="Regime" value={m.regime ?? "n/a"} />
              <Stat label="Feed ready" value={m.ready ? "yes" : "no"} />
              <Stat label="Features" value={String(Object.keys(m.features ?? {}).length)} />
              <Stat label="Broker" value={m.broker} />
            </div>
          )}
        </DataView>
      </Card>
      <div className="grid-2">
        <Card title="Regime results" badge={<DomainBadge domain="virtual" />}>
          <DataView state={virt}>{(d) => <RegimeTable byRegime={d.metrics?.by_regime} />}</DataView>
        </Card>
        <Card title="Regime results" badge={<DomainBadge domain="historical" />}>
          <DataView state={hist}>{(d) => <RegimeTable byRegime={d.metrics?.by_regime} />}</DataView>
        </Card>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- institutional

export function InstitutionalPage() {
  const st = useApi(api.institutional, [], 30000);
  return (
    <>
      <PageHeader title="Institutional Intelligence" subtitle="Positioning / flow features, when a data source is configured." />
      <Card title="Institutional features">
        <DataView state={st}>
          {(d) =>
            d.available ? (
              <KVTable data={d.features} emptyText="Source available but no features reported yet." />
            ) : (
              <Empty>
                Not available{d.reason ? `: ${d.reason}` : "."} No institutional values are shown or used.
              </Empty>
            )
          }
        </DataView>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- news

export function NewsPage() {
  const st = useApi(api.news, [], 60000);
  return (
    <>
      <PageHeader title="Global News" subtitle="Economic calendar and news events affecting gold." />
      <DataView state={st}>
        {(n) => (
          <>
            <Card title="News blackout">
              <Pill tone={n.blackout_active ? "bad" : "ok"}>{n.blackout_active ? "BLACKOUT ACTIVE - new entries blocked" : "No blackout"}</Pill>
            </Card>
            <Card title="Events">
              <Table
                rows={n.events ?? []}
                rowKey={(e, i) => `${e.time}-${i}`}
                empty="No news events reported."
                columns={[
                  { key: "time", label: "Time", render: (e) => fmtTime(e.time) },
                  { key: "title", label: "Title" },
                  { key: "category", label: "Category" },
                  { key: "impact", label: "Impact", render: (e) => (e.impact ? <Pill tone={toneFor(e.impact === "high" ? "fail" : e.impact === "medium" ? "warn" : "neutral")}>{e.impact}</Pill> : "n/a") },
                  { key: "uncertainty", label: "Uncertainty", className: "num", render: (e) => fmtValue(e.uncertainty) },
                ]}
              />
            </Card>
            {Object.keys(n).some((k) => !["events", "blackout_active"].includes(k)) && (
              <Card title="Other fields">
                <JsonBlock value={Object.fromEntries(Object.entries(n).filter(([k]) => !["events", "blackout_active"].includes(k)))} />
              </Card>
            )}
          </>
        )}
      </DataView>
    </>
  );
}
