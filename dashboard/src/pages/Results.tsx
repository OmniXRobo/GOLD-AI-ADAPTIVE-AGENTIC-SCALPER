import { useMemo, useState } from "react";
import { DOMAIN_TITLE, type Domain, type Trade } from "../api";
import { useTrades } from "../components/domain";
import { Card, DataView, DomainBadge, Empty, PageHeader } from "../components/ui";
import { fmtMoney, fmtNum, humanize, signClass } from "../lib";
import { canonical, instrumentChoices, instrumentLabel, pipText, priceDigits, SymbolChips, useInstruments } from "../instruments";
import { STYLE_INFO, StyleChips, styleOf, StyleTag, type TradeStyle } from "../styles";
import { holdTime, inPeriod, periodStats, PERIODS, tradePips, type Period, type PeriodStats } from "../results";

function shortTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className={`tile-value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  );
}

function Summary({ s }: { s: PeriodStats }) {
  return (
    <>
      <div className="pip-banner">
        <span className="pos">Gain +{fmtNum(s.pipsWon, 0)} pips</span>
        <span className="neg">Loss −{fmtNum(s.pipsLost, 0)} pips</span>
      </div>
      <div className="tiles">
        <Tile label="Closed trades" value={String(s.trades)} />
        <Tile label="Win rate" value={s.winRate === null ? "n/a" : `${Math.round(s.winRate * 100)}%`} sub={`${s.wins} won / ${s.losses} lost`} />
        <Tile label="Net" value={`${s.netPips > 0 ? "+" : ""}${fmtNum(s.netPips, 0)} pips`} sub={fmtMoney(s.netPnl)} tone={signClass(s.netPips)} />
        <Tile label="Break-even" value={String(s.breakeven)} sub="within 1 pip" />
        <Tile label="Over 30 pips" value={String(s.over30)} tone={s.over30 ? "pos" : ""} />
        <Tile label="Over 50 pips" value={String(s.over50)} tone={s.over50 ? "pos" : ""} />
      </div>
    </>
  );
}

function History({ trades }: { trades: Trade[] }) {
  const rows = [...trades].sort((a, b) => String(b.exit_time).localeCompare(String(a.exit_time))).slice(0, 50);
  if (!rows.length) return <Empty>No closed trades in this period.</Empty>;
  return (
    <div className="hist">
      {rows.map((t) => {
        const p = tradePips(t);
        const side = String(t.side).toUpperCase();
        const result = p !== null && Math.abs(p) < 1 ? "be" : t.net_pnl > 0 ? "win" : "loss";
        const held = holdTime(t);
        const n = priceDigits(t.symbol);
        return (
          <div className={`hist-row hist-${result}`} key={t.trade_id}>
            <div className="hist-top">
              <span className={`signal-side ${side === "BUY" ? "buy" : "sell"}`}>{side}</span>
              <b>{instrumentLabel(t.symbol)}</b>
              <StyleTag style={styleOf(t)} />
              <span className="muted small">{t.symbol}</span>
              <b className={`hist-pips ${signClass(p)}`}>{p === null ? "n/a" : `${p > 0 ? "+" : ""}${fmtNum(p, 0)} pips`}</b>
            </div>
            <div className="hist-levels">
              <span>
                Entry <b>{fmtNum(t.entry_price, n)}</b>
              </span>
              <span>
                SL <b>{fmtNum(t.stop_loss, n)}</b>
              </span>
              <span>
                TP <b>{fmtNum(t.take_profit, n)}</b>
              </span>
              <span>
                Exit <b>{fmtNum(t.exit_price, n)}</b>
              </span>
            </div>
            <div className="hist-foot">
              <span className="muted small">
                {shortTime(t.entry_time)} · {t.exit_reason ? humanize(String(t.exit_reason)) : "Closed"}
                {held ? ` after ${held}` : ""} · {fmtMoney(t.net_pnl)}
              </span>
              <span className={`result-tag tag-${result}`}>{result === "win" ? "Profit" : result === "loss" ? "Loss" : "Break-even"}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function ResultsPage() {
  const [domain, setDomain] = useState<Domain>("virtual");
  const [period, setPeriod] = useState<Period>("week");
  const [sym, setSym] = useState<string | null>(null);
  const [style, setStyle] = useState<TradeStyle | null>(null);
  const st = useTrades(domain, 5000, 60000);
  const running = useInstruments(60000);
  const choices = useMemo(() => instrumentChoices(running.data, (st.data?.trades ?? []).map((t) => t.symbol)), [running.data, st.data]);
  const trades = useMemo(
    () =>
      st.data
        ? inPeriod(st.data.trades, period).filter((t) => (sym === null || canonical(t.symbol) === sym) && (style === null || styleOf(t) === style))
        : [],
    [st.data, period, sym, style],
  );
  const label = PERIODS.find(([k]) => k === period)?.[1] ?? "";
  const pipNote = sym ? `${pipText(sym)}.` : "Pips are counted in each trade's own instrument (gold $0.10, Bitcoin $1, forex 0.0001, JPY pairs 0.01), so the all-markets total mixes instruments.";
  return (
    <>
      <PageHeader title="Results" subtitle="Win rate and pips from trades that actually closed. Nothing is estimated or rounded up." />
      <div className="seg">
        {(["virtual", "real"] as Domain[]).map((d) => (
          <button key={d} className={`seg-btn ${domain === d ? "active" : ""}`} onClick={() => setDomain(d)}>
            {d === "virtual" ? "AI virtual trading" : "Real account"}
          </button>
        ))}
      </div>
      <SymbolChips choices={choices} value={sym} onChange={setSym} allLabel="All markets" />
      <StyleChips value={style} onChange={setStyle} />
      <div className="chips chips-scroll">
        {PERIODS.map(([k, l]) => (
          <button key={k} className={`chip ${period === k ? "active" : ""}`} onClick={() => setPeriod(k)}>
            {l}
          </button>
        ))}
      </div>
      <Card title={`${sym ? `${instrumentLabel(sym)} · ` : ""}${style ? `${STYLE_INFO[style].label} · ` : ""}${label} · ${DOMAIN_TITLE[domain]}`} badge={<DomainBadge domain={domain} />}>
        <DataView state={st}>{() => <Summary s={periodStats(trades)} />}</DataView>
        <p className="muted small">
          {pipNote} Win rate counts a trade as won only if it made money after costs.{" "}
          {domain === "virtual" ? "Virtual fills are estimated from the live price; no real money." : "Real fills from the broker."}
        </p>
      </Card>
      <Card title="Trade history">
        <DataView state={st}>{() => <History trades={trades} />}</DataView>
      </Card>
    </>
  );
}
