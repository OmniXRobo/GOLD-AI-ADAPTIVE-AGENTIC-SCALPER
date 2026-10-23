import { Link } from "react-router-dom";
import { api } from "../api";
import { useTrades } from "../components/domain";
import { Icon } from "../components/icons";
import { Card, DataView, Empty, PageHeader, Pill } from "../components/ui";
import { fmtDuration, fmtMoney, fmtNum, fmtPct, fmtTime, humanize, signClass, useApi } from "../lib";
import { useLive } from "../state";

const RISK_KEYS = ["risk_per_trade_pct", "max_lots_per_trade", "max_daily_loss_pct", "max_drawdown_pct", "max_open_positions", "min_risk_reward", "min_confidence", "max_spread_points"];

function ModeRow({ title, detail, state, tone }: { title: string; detail: string; state: string; tone: "ok" | "warn" | "bad" | "neutral" }) {
  return (
    <div className="mode-row">
      <div>
        <div className="mode-title">{title}</div>
        <div className="muted small">{detail}</div>
      </div>
      <Pill tone={tone}>{state}</Pill>
    </div>
  );
}

export default function AutopilotPage() {
  const { overview, auth } = useLive();
  const risk = useApi(api.risk, [], 30000);
  const engines = overview?.virtual_engines ?? [];
  const real = auth?.real_trading_enabled ?? overview?.real_trading_enabled;
  const virt = useTrades("virtual", 200, 60000);
  const m = virt.data?.metrics;
  const open = engines.reduce((a, e) => a + (typeof e.open_positions === "number" ? e.open_positions : 0), 0);
  const equity = engines.length === 1 ? engines[0].equity : undefined;

  return (
    <>
      <PageHeader title="Autopilot" subtitle="What the AI is doing right now, and what it is allowed to do." />

      <Card
        title="Trading performance"
        badge={<span className="muted small">AI virtual account</span>}
        actions={
          <Link to="/results" className="small">
            Results
          </Link>
        }
      >
        <div className="perf">
          <div>
            <div className="tile-label">Total profit</div>
            <div className={`perf-value ${signClass(m?.net_profit)}`}>{m?.total_trades ? fmtMoney(m.net_profit) : "n/a"}</div>
          </div>
          <div>
            <div className="tile-label">Open trades</div>
            <div className="perf-value">{overview ? open : "..."}</div>
          </div>
          <div>
            <div className="tile-label">Win rate</div>
            <div className="perf-value">{m?.total_trades ? fmtPct(m.win_rate) : "n/a"}</div>
          </div>
        </div>
        <div className="perf-rows">
          <div>
            <span>Closed trades</span>
            <b>{m ? m.total_trades : virt.error ? "n/a" : "..."}</b>
          </div>
          <div>
            <span>Virtual balance</span>
            <b>{typeof equity === "number" ? fmtNum(equity) : "n/a"}</b>
          </div>
        </div>
        <p className="muted small">Recorded virtual trades only, with estimated fills. No real money is traded.</p>
      </Card>

      <Card title="AI engines">
        {!overview ? (
          <div className="state state-loading">Loading...</div>
        ) : engines.length ? (
          <div className="engine-list">
            {engines.map((e, i) => (
              <div className="engine" key={`${e.broker}-${i}`}>
                <div className="engine-head">
                  <span className="engine-dot" aria-hidden="true" />
                  <b>
                    {e.symbol} · {e.broker}
                  </b>
                  <span className="muted small mono">{e.model_version ?? ""}</span>
                </div>
                <div className="stats">
                  <div className="stat">
                    <div className="stat-label">Learning for</div>
                    <div className="stat-value">{fmtDuration(e.learning_started)}</div>
                  </div>
                  <div className="stat">
                    <div className="stat-label">Ticks read</div>
                    <div className="stat-value">{typeof e.ticks_processed === "number" ? e.ticks_processed.toLocaleString() : "n/a"}</div>
                  </div>
                  <div className="stat">
                    <div className="stat-label">Decisions</div>
                    <div className="stat-value">{typeof e.decisions === "number" ? e.decisions.toLocaleString() : "n/a"}</div>
                  </div>
                  <div className="stat">
                    <div className="stat-label">Open virtual trades</div>
                    <div className="stat-value">{e.open_positions ?? "n/a"}</div>
                  </div>
                  <div className="stat">
                    <div className="stat-label">Virtual equity</div>
                    <div className="stat-value">{fmtNum(e.equity)}</div>
                  </div>
                  <div className="stat">
                    <div className="stat-label">Last tick</div>
                    <div className="stat-value small">{fmtTime(e.last_tick)}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty>No AI engine is running. Start the service with an MT5 terminal to begin live virtual trading.</Empty>
        )}
      </Card>

      <Card title="Execution modes">
        <ModeRow title="Signals and alerts" detail="New trade ideas are sent to the dashboard, the phone app and configured channels." state="on" tone="ok" />
        <ModeRow
          title="Virtual autopilot"
          detail="The AI trades a virtual account on the live price and learns from every closed trade."
          state={engines.length ? "running" : "stopped"}
          tone={engines.length ? "ok" : "warn"}
        />
        <ModeRow
          title="Demo account auto-execution"
          detail="Sends orders to a broker demo account."
          state={overview?.demo_execution_enabled ? "enabled" : "off"}
          tone={overview?.demo_execution_enabled ? "warn" : "neutral"}
        />
        <ModeRow
          title="Real money auto-execution"
          detail="Locked until the owner signs a time-limited grant."
          state={real ? "ENABLED" : "locked"}
          tone={real ? "bad" : "neutral"}
        />
        <p className="small">
          <Link to="/modes">Trading modes</Link> · <Link to="/authorization">Owner authorization</Link> · <Link to="/maturity">AI maturity</Link>
        </p>
      </Card>

      <Card
        title="Risk guard"
        actions={
          <Link to="/risk" className="small">
            Details
          </Link>
        }
      >
        <DataView state={risk}>
          {(r) => {
            const rows = RISK_KEYS.filter((k) => r.config?.[k] !== undefined);
            return rows.length ? (
              <div className="stats">
                {rows.map((k) => (
                  <div className="stat" key={k}>
                    <div className="stat-label">{humanize(k)}</div>
                    <div className="stat-value">{String(r.config[k])}</div>
                  </div>
                ))}
              </div>
            ) : (
              <Empty>Risk limits not reported.</Empty>
            );
          }}
        </DataView>
        <p className="muted small">
          <Icon name="risk" size={14} /> No martingale, grid or recovery sizing. Every trade is checked by the independent risk engine.
        </p>
      </Card>
    </>
  );
}
