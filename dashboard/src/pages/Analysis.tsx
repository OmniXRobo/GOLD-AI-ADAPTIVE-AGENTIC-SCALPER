import { useMemo, useState } from "react";
import { api, type NewsEvent, type Technical } from "../api";
import { Card, DataView, Empty, PageHeader, Pill } from "../components/ui";
import { instrumentChoices, priceDigits, SymbolChips, useInstruments } from "../instruments";
import { fmtNum, fmtTime, humanize, useApi } from "../lib";

type Tab = "technical" | "fundamental" | "calendar";
const TFS = ["M5", "M15", "H1", "H4"];

function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: T[]; onChange: (v: T) => void; label?: (v: T) => string }) {
  return (
    <div className="chips" role="tablist">
      {options.map((o) => (
        <button key={o} role="tab" aria-selected={value === o} className={`chip ${value === o ? "active" : ""}`} onClick={() => onChange(o)}>
          {label ? label(o) : o}
        </button>
      ))}
    </div>
  );
}

/** Semicircle gauge for a score in [-1, 1]. */
function arc(from: number, to: number): string {
  // angles in degrees, 180 = left end, 0 = right end, centre (50, 50), radius 40
  const pt = (deg: number) => `${(50 + 40 * Math.cos((deg * Math.PI) / 180)).toFixed(2)} ${(50 - 40 * Math.sin((deg * Math.PI) / 180)).toFixed(2)}`;
  return `M${pt(from)} A40 40 0 0 1 ${pt(to)}`;
}

function Gauge({ score }: { score: number | null }) {
  const s = Math.max(-1, Math.min(1, score ?? 0));
  const a = Math.PI * (1 - (s + 1) / 2);
  const x = 50 + 32 * Math.cos(a);
  const y = 50 - 32 * Math.sin(a);
  return (
    <svg viewBox="0 0 100 56" className="gauge" role="img" aria-label={score === null ? "No score" : `Score ${s.toFixed(2)}`}>
      <path d={arc(180, 122)} stroke="var(--neg)" />
      <path d={arc(118, 62)} stroke="var(--warn-fg)" />
      <path d={arc(58, 0)} stroke="var(--pos)" />
      {score !== null && <line x1="50" y1="50" x2={x} y2={y} className="gauge-needle" />}
      <circle cx="50" cy="50" r="3.5" className="gauge-hub" />
    </svg>
  );
}

function Meter({ label, value, min, max, zones, hint }: { label: string; value: number | null; min: number; max: number; zones: [number, number]; hint: string }) {
  const pct = value === null ? null : Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
  const z1 = ((zones[0] - min) / (max - min)) * 100;
  const z2 = ((zones[1] - min) / (max - min)) * 100;
  return (
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <b>{value === null ? "n/a" : fmtNum(value, 2)}</b>
      </div>
      <div className="meter-bar" style={{ background: `linear-gradient(90deg, var(--pos) 0 ${z1}%, var(--warn-fg) ${z1}% ${z2}%, var(--neg) ${z2}% 100%)` }}>
        {pct !== null && <i style={{ left: `${pct}%` }} />}
      </div>
      <div className="muted small">{hint}</div>
    </div>
  );
}

function sentimentTone(label: string): "ok" | "bad" | "warn" | "neutral" {
  if (label.includes("bullish")) return "ok";
  if (label.includes("bearish")) return "bad";
  if (label === "neutral") return "warn";
  return "neutral";
}

function TechnicalTab() {
  const [tf, setTf] = useState("H1");
  const running = useInstruments(60000);
  const choices = instrumentChoices(running.data);
  const [sym, setSym] = useState<string | null>(null);
  const st = useApi(() => api.technical(tf, sym), [tf, sym], 15000);
  return (
    <>
      {choices.length > 1 && <SymbolChips choices={choices} value={sym ?? choices[0]} onChange={setSym} allLabel={null} />}
      <Seg value={tf} options={TFS} onChange={setTf} />
      <DataView state={st}>{(t) => <TechnicalView t={t} />}</DataView>
    </>
  );
}

function TechnicalView({ t }: { t: Technical }) {
  const missing = Object.entries(t.bars_missing);
  const n = priceDigits(t.symbol);
  const rsiZone = t.rsi14 === null ? "" : t.rsi14 > 70 ? "Overbought" : t.rsi14 < 30 ? "Oversold" : "Neutral";
  return (
    <>
      <Card className="card-hero">
        <div className="tech-head">
          <div>
            <div className="muted small">
              {t.symbol} · {t.timeframe} · {t.bars} closed bars
            </div>
            <div className="price-big">{fmtNum(t.last_close, n)}</div>
            <Pill tone={sentimentTone(t.label)}>{humanize(t.label)}</Pill>
          </div>
          <Gauge score={t.score} />
        </div>
        <div className="price-sub">
          <span>
            Support <b>{fmtNum(t.support, n)}</b>
          </span>
          <span>
            Resistance <b>{fmtNum(t.resistance, n)}</b>
          </span>
          <span>
            MA50 <b>{fmtNum(t.ma50, n)}</b>
          </span>
          <span>
            MA200 <b>{fmtNum(t.ma200, n)}</b>
          </span>
        </div>
        <p className="muted small">
          Sentiment combines RSI, MACD, Stochastic and the 50/200 moving averages ({Object.keys(t.votes).length} voting now). {t.note}
        </p>
      </Card>

      <Card title="Momentum and flow">
        {t.pressure ? (
          <div className="pressure">
            <div className="meter-head">
              <span className="pos">Buy {fmtNum(t.pressure.buy_pct, 0)}%</span>
              <span className="neg">Sell {fmtNum(t.pressure.sell_pct, 0)}%</span>
            </div>
            <div className="pressure-bar">
              <i style={{ width: `${t.pressure.buy_pct}%` }} />
            </div>
            <div className="muted small">Share of up versus down candle bodies over the last {t.pressure.bars} bars. Not order flow.</div>
          </div>
        ) : (
          <Empty>Buy/sell pressure needs {t.bars_missing.pressure ?? 0} more bars.</Empty>
        )}
        <Meter label="RSI (14)" value={t.rsi14} min={0} max={100} zones={[30, 70]} hint={rsiZone || "Needs more bars"} />
        <Meter label="Stochastic %K" value={t.stochastic?.k ?? null} min={0} max={100} zones={[20, 80]} hint={t.stochastic ? `%D ${fmtNum(t.stochastic.d, 2)}` : "Needs more bars"} />
        <div className="stats">
          <div className="stat">
            <div className="stat-label">MACD histogram</div>
            <div className={`stat-value ${t.macd ? (t.macd.histogram > 0 ? "pos" : "neg") : ""}`}>{t.macd ? fmtNum(t.macd.histogram, 3) : "n/a"}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Bollinger upper</div>
            <div className="stat-value">{fmtNum(t.bollinger?.upper, n)}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Bollinger lower</div>
            <div className="stat-value">{fmtNum(t.bollinger?.lower, n)}</div>
          </div>
        </div>
        {missing.length > 0 && (
          <p className="muted small">
            Still building history on {t.timeframe}: {missing.map(([k, n]) => `${humanize(k)} needs ${n} more bars`).join(", ")}.
          </p>
        )}
      </Card>
    </>
  );
}

// Released US data: which way did it surprise? Higher inflation/growth/jobs usually lifts the dollar and weighs on gold.
const USD_POSITIVE_WHEN_HIGHER = new Set(["cpi", "ppi", "nfp", "pce", "gdp"]);
const USD_POSITIVE_WHEN_LOWER = new Set(["unemployment", "jobless_claims"]);

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function surprise(e: NewsEvent): "above" | "below" | "inline" | null {
  const a = num(e.actual);
  const f = num(e.forecast);
  if (a === null || f === null) return null;
  if (Math.abs(a - f) < 1e-9) return "inline";
  return a > f ? "above" : "below";
}

function goldRead(e: NewsEvent): -1 | 1 | 0 {
  const s = surprise(e);
  const c = String(e.category ?? "");
  if (!s || s === "inline" || String(e.currency ?? "USD").toUpperCase() !== "USD") return 0;
  if (USD_POSITIVE_WHEN_HIGHER.has(c)) return s === "above" ? -1 : 1;
  if (USD_POSITIVE_WHEN_LOWER.has(c)) return s === "below" ? -1 : 1;
  return 0;
}

function FundamentalTab() {
  const st = useApi(api.news, [], 60000);
  return (
    <DataView state={st}>
      {(n) => {
        const now = Date.now();
        const released = n.events.filter((e) => Date.parse(e.time) <= now && surprise(e) !== null);
        const reads = released.map(goldRead).filter((r) => r !== 0);
        const net = reads.reduce<number>((a, b) => a + b, 0);
        const nextHigh = n.events.filter((e) => e.impact === "high" && Date.parse(e.time) > now).sort((a, b) => a.time.localeCompare(b.time))[0];
        const fed = n.events.filter((e) => e.category === "fomc" || e.category === "fed_speech").sort((a, b) => a.time.localeCompare(b.time));
        const flags = (n.flags ?? {}) as Record<string, number>;
        return (
          <>
            <Card title="US data surprise bias">
              {reads.length ? (
                <>
                  <div className="bias-row">
                    <Pill tone={net > 0 ? "ok" : net < 0 ? "bad" : "warn"}>{net > 0 ? "Gold-supportive" : net < 0 ? "Gold-negative" : "Mixed"}</Pill>
                    <span className="muted small">
                      {reads.filter((r) => r > 0).length} supportive · {reads.filter((r) => r < 0).length} negative, from {reads.length} released US releases with a forecast
                    </span>
                  </div>
                  <p className="muted small">
                    Rule of thumb: inflation, jobs or growth above forecast usually strengthen the dollar and weigh on gold, and the reverse supports it. This is a typical reaction, not a
                    prediction, and the AI does not trade on it.
                  </p>
                </>
              ) : (
                <Empty>No released US data with both actual and forecast in the loaded calendar window.</Empty>
              )}
            </Card>
            <Card title="Event risk now">
              <div className="stats">
                <div className="stat">
                  <div className="stat-label">News blackout</div>
                  <div className={`stat-value ${n.blackout_active ? "neg" : ""}`}>{n.blackout_active ? "ACTIVE" : "off"}</div>
                </div>
                <div className="stat">
                  <div className="stat-label">Next high-impact</div>
                  <div className="stat-value small">{nextHigh ? nextHigh.title : "none loaded"}</div>
                  {nextHigh && <div className="stat-hint">{fmtTime(nextHigh.time)}</div>}
                </div>
                <div className="stat">
                  <div className="stat-label">Inside an event window</div>
                  <div className="stat-value">{flags.news_pre_event_high || flags.news_post_event_high ? "high impact" : flags.news_pre_event_medium || flags.news_post_event_medium ? "medium" : "no"}</div>
                </div>
              </div>
            </Card>
            <Card title="Fed watch">
              {fed.length ? (
                <ul className="event-list">
                  {fed.slice(-6).map((e, i) => (
                    <li key={i}>
                      <span className="mono small">{fmtTime(e.time)}</span> {e.title}
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>No Fed decisions or speeches in the loaded calendar window.</Empty>
              )}
              <p className="muted small">Rate-hike odds, Treasury yields and the dollar index need a market-data source that is not connected yet, so they are not shown.</p>
            </Card>
          </>
        );
      }}
    </DataView>
  );
}

type Impact = "all" | "high" | "medium" | "low";

function CalendarTab() {
  const st = useApi(api.news, [], 60000);
  const [imp, setImp] = useState<Impact>("all");
  return (
    <>
      <Seg value={imp} options={["all", "high", "medium", "low"] as Impact[]} onChange={setImp} label={(v) => humanize(v)} />
      <DataView state={st} isEmpty={(n) => !n.events.length} empty="No calendar events loaded. Check the calendar source on the System Health page.">
        {(n) => <CalendarList events={n.events} impact={imp} />}
      </DataView>
    </>
  );
}

function CalendarList({ events, impact }: { events: NewsEvent[]; impact: Impact }) {
  const days = useMemo(() => {
    const rows = events.filter((e) => impact === "all" || e.impact === impact).sort((a, b) => a.time.localeCompare(b.time));
    const out = new Map<string, NewsEvent[]>();
    for (const e of rows) {
      const d = new Date(e.time).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
      out.set(d, [...(out.get(d) ?? []), e]);
    }
    return [...out.entries()];
  }, [events, impact]);
  if (!days.length) return <Empty>No {impact} impact events in the loaded window.</Empty>;
  return (
    <>
      {days.map(([day, rows]) => (
        <Card key={day} title={day}>
          <div className="cal">
            {rows.map((e, i) => {
              const s = surprise(e);
              return (
                <div className="cal-row" key={i}>
                  <div className="cal-time">
                    {new Date(e.time).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                    <span className={`impact impact-${e.impact || "none"}`}>{e.impact || "n/a"}</span>
                  </div>
                  <div className="cal-body">
                    <div className="cal-title">
                      <b>{e.currency ?? ""}</b> {e.title}
                      {s && <span className={`pill ${s === "inline" ? "pill-neutral" : "pill-info"}`}>{s === "inline" ? "In line" : s === "above" ? "Above forecast" : "Below forecast"}</span>}
                    </div>
                    <div className="cal-nums">
                      <span>
                        Actual <b>{e.actual ?? "-"}</b>
                      </span>
                      <span>
                        Forecast <b>{e.forecast ?? "-"}</b>
                      </span>
                      <span>
                        Previous <b>{e.previous ?? "-"}</b>
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      ))}
    </>
  );
}

export default function AnalysisPage() {
  const [tab, setTab] = useState<Tab>("technical");
  return (
    <>
      <PageHeader title="Market analysis" subtitle="Built from the server's own candles and economic calendar. Times are shown in your device's time zone." />
      <div className="tabs" role="tablist">
        {(["technical", "fundamental", "calendar"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {humanize(t)}
          </button>
        ))}
      </div>
      {tab === "technical" && <TechnicalTab />}
      {tab === "fundamental" && <FundamentalTab />}
      {tab === "calendar" && <CalendarTab />}
    </>
  );
}
