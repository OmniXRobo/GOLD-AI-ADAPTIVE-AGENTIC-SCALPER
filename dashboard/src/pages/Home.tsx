import { Link } from "react-router-dom";
import { api, type NewsEvent } from "../api";
import { useTrades } from "../components/domain";
import { Icon } from "../components/icons";
import { latestSignals, SignalCard } from "../components/SignalCard";
import { DomainBadge, Empty } from "../components/ui";
import { fmtMoney, fmtNum, fmtPct, fmtTime, signClass, useApi } from "../lib";
import { useLive } from "../state";

function PriceHero() {
  const st = useApi(api.market, [], 3000);
  const m = st.data;
  const lt = m?.last_tick;
  return (
    <section className="hero-price">
      <div className="hero-price-top">
        <div>
          <div className="hero-sym">{m?.symbol ?? "XAUUSD"}</div>
          <div className="hero-sub">{m ? `Live · ${m.broker}` : "Live price"}</div>
        </div>
        {m && <span className={`pill ${m.ready ? "pill-ok" : "pill-warn"}`}>{m.ready ? "AI ready" : "AI warming up"}</span>}
      </div>
      {lt ? (
        <>
          <div className="hero-px">{fmtNum(lt.bid, 2)}</div>
          <div className="hero-meta">
            <span>
              Ask <b>{fmtNum(lt.ask, 2)}</b>
            </span>
            <span>
              Spread <b>{fmtNum(lt.spread, 2)}</b>
            </span>
            <span>
              Regime <b>{m?.regime ?? "n/a"}</b>
            </span>
            <span>{fmtTime(lt.time)}</span>
          </div>
        </>
      ) : (
        <p className="hero-empty">{st.error ? `No live price: ${st.error}` : m ? "Waiting for the first tick." : "Loading..."}</p>
      )}
    </section>
  );
}

function untilText(ms: number): string {
  const m = Math.max(0, Math.round(ms / 60000));
  if (m < 60) return `in ${m}m`;
  if (m < 48 * 60) return `in ${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
  return `in ${Math.round(m / 1440)} days`;
}

/** The next medium or high impact calendar release, from the server's own calendar feed. */
function NextEvent() {
  const st = useApi(api.news, [], 60000);
  const now = Date.now();
  const next: NewsEvent | undefined = (st.data?.events ?? [])
    .filter((e) => Date.parse(e.time) > now && (e.impact === "high" || e.impact === "medium"))
    .sort((a, b) => a.time.localeCompare(b.time))[0];
  if (!next) return null;
  return (
    <>
      <div className="section-head">
        <h2>Next economic event</h2>
        <Link to="/analysis" className="small">
          Calendar
        </Link>
      </div>
      <Link to="/analysis" className="event-card">
        <div className="event-top">
          <b>{new Date(next.time).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</b>
          <span>
            {next.currency ?? ""} · {untilText(Date.parse(next.time) - now)}
          </span>
          <span className={`impact impact-${next.impact}`}>{next.impact}</span>
        </div>
        <div className="event-title">{next.title}</div>
        <div className="cal-nums">
          <span>
            Actual <b>{next.actual ?? "-"}</b>
          </span>
          <span>
            Forecast <b>{next.forecast ?? "-"}</b>
          </span>
          <span>
            Previous <b>{next.previous ?? "-"}</b>
          </span>
        </div>
      </Link>
    </>
  );
}

function QuickLink({ to, icon, label, hint }: { to: string; icon: string; label: string; hint: string }) {
  return (
    <Link to={to} className="quick">
      <span className="quick-icon">
        <Icon name={icon} size={20} />
      </span>
      <span className="quick-label">{label}</span>
      <span className="quick-hint">{hint}</span>
    </Link>
  );
}

export default function HomePage() {
  const { overview } = useLive();
  const sig = useApi(api.signals, [], 10000);
  const virt = useTrades("virtual", 200, 60000);
  const latest = latestSignals(sig.data, 3);
  const m = virt.data?.metrics;
  const engines = overview?.virtual_engines ?? [];

  return (
    <>
      <PriceHero />

      <div className="section-head">
        <h2>Latest signals</h2>
        <Link to="/signals" className="small">
          All signals
        </Link>
      </div>
      {sig.error ? (
        <Empty>Signals unavailable: {sig.error}</Empty>
      ) : latest.length ? (
        <div className="signal-list">
          {latest.map((s, i) => (
            <SignalCard key={String(s.id)} s={s} compact={i > 0} />
          ))}
        </div>
      ) : (
        <Empty>{sig.data ? "No signals yet. The AI only proposes a trade when its checks pass." : "Loading..."}</Empty>
      )}

      <NextEvent />

      <div className="section-head">
        <h2>AI virtual trading results</h2>
        <DomainBadge domain="virtual" />
      </div>
      <div className="stats stats-3">
        <div className="stat">
          <div className="stat-label">Closed trades</div>
          <div className="stat-value">{m ? m.total_trades : virt.error ? "n/a" : "..."}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Win rate</div>
          <div className="stat-value">{m?.total_trades ? fmtPct(m.win_rate) : "n/a"}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Net P/L</div>
          <div className={`stat-value ${signClass(m?.net_profit)}`}>{m?.total_trades ? fmtMoney(m.net_profit) : "n/a"}</div>
        </div>
      </div>
      <p className="muted small">
        Recorded virtual trades only (estimated fills, no real money). Nothing is shown until trades have actually closed.
      </p>

      <div className="quick-grid">
        <QuickLink to="/autopilot" icon="agent" label="Autopilot" hint={engines.length ? `${engines.length} engine running` : "engine status"} />
        <QuickLink to="/analysis" icon="performance" label="Analysis" hint="technical, news, calendar" />
        <QuickLink to="/practice" icon="practice" label="Practice" hint="paper trade the live price" />
        <QuickLink to="/results" icon="backtesting" label="Results" hint="win rate and pips by period" />
        <QuickLink to="/learn" icon="news" label="Learn" hint="guide, calculator, FAQ" />
        <QuickLink to="/risk" icon="risk" label="Risk" hint={overview?.emergency_stop ? "emergency stop ACTIVE" : "limits and stop"} />
      </div>
    </>
  );
}
