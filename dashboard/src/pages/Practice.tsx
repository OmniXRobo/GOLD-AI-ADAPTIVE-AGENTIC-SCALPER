import { useEffect, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Signal } from "../api";
import { latestSignals, SignalCard } from "../components/SignalCard";
import { Card, ConfirmDialog, Empty, PageHeader } from "../components/ui";
import { fmtMoney, fmtNum, fmtTime, signClass, useApi } from "../lib";

/**
 * Practice mode: paper trading on the live price, kept only in this browser.
 * It is not part of any AI memory and never reaches a broker.
 */
const KEY = "gold_ai_practice_v1";
const OZ_PER_LOT = 100; // standard XAUUSD contract; brokers can differ
const BALANCES = [100, 500, 1000, 5000];

interface Position {
  id: number;
  side: "buy" | "sell";
  lots: number;
  entry: number;
  sl: number | null;
  tp: number | null;
  opened: string;
}
interface Closed extends Position {
  exit: number;
  pnl: number;
  closed: string;
  reason: string;
}
interface Practice {
  start: number;
  balance: number;
  lot: number;
  open: Position[];
  history: Closed[];
}

function load(): Practice | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v ? (JSON.parse(v) as Practice) : null;
  } catch {
    return null;
  }
}
function save(p: Practice | null) {
  try {
    if (p) window.localStorage.setItem(KEY, JSON.stringify(p));
    else window.localStorage.removeItem(KEY);
  } catch {
    /* storage blocked: practice still works for this visit */
  }
}

function pnl(p: Position, bid: number, ask: number): number {
  const exit = p.side === "buy" ? bid : ask;
  return (p.side === "buy" ? exit - p.entry : p.entry - exit) * p.lots * OZ_PER_LOT;
}

function Setup({ onStart }: { onStart: (balance: number, lot: number) => void }) {
  const [bal, setBal] = useState(1000);
  const [lot, setLot] = useState(0.1);
  return (
    <Card className="practice-setup">
      <h2>Practice trading</h2>
      <p className="muted small">Paper trade XAUUSD on the live price. Practice money only; nothing here reaches a broker or the AI's memory.</p>
      <label className="field">
        <span>Starting balance (USD)</span>
        <input type="number" min={10} value={bal} onChange={(e) => setBal(Math.max(10, Number(e.target.value) || 0))} />
      </label>
      <div className="chips">
        {BALANCES.map((b) => (
          <button key={b} className={`chip ${bal === b ? "active" : ""}`} onClick={() => setBal(b)}>
            ${b.toLocaleString()}
          </button>
        ))}
      </div>
      <LotPicker lot={lot} setLot={setLot} />
      <button className="btn btn-primary btn-block" onClick={() => onStart(bal, lot)}>
        Start practice
      </button>
    </Card>
  );
}

function LotPicker({ lot, setLot }: { lot: number; setLot: (n: number) => void }) {
  const step = (d: number) => setLot(Math.min(5, Math.max(0.01, Math.round((lot + d) * 100) / 100)));
  return (
    <div className="lot">
      <span className="stat-label">Lot size</span>
      <button className="btn btn-icon" onClick={() => step(-0.01)} aria-label="Smaller lot">
        −
      </button>
      <b>{lot.toFixed(2)}</b>
      <button className="btn btn-icon" onClick={() => step(0.01)} aria-label="Larger lot">
        +
      </button>
      <span className="muted small">${fmtNum(lot * OZ_PER_LOT, 0)} per $1 move</span>
    </div>
  );
}

export default function PracticePage() {
  const [p, setP] = useState<Practice | null>(load);
  const [reset, setReset] = useState(false);
  const [useSig, setUseSig] = useState(true);
  const mkt = useApi(api.market, [], 2000);
  const sig = useApi(api.signals, [], 15000);
  const [ticks, setTicks] = useState<{ t: string; bid: number }[]>([]);
  const lt = mkt.data?.last_tick ?? null;
  const pRef = useRef(p);
  pRef.current = p;

  const update = (next: Practice | null) => {
    setP(next);
    save(next);
  };

  // Record ticks for the chart and close positions whose SL/TP the live price has crossed.
  useEffect(() => {
    if (!lt || typeof lt.bid !== "number") return;
    setTicks((prev) => (prev.length && prev[prev.length - 1].t === lt.time ? prev : [...prev.slice(-299), { t: lt.time, bid: lt.bid }]));
    const cur = pRef.current;
    if (!cur || !cur.open.length) return;
    const hits: Closed[] = [];
    const keep: Position[] = [];
    for (const pos of cur.open) {
      const px = pos.side === "buy" ? lt.bid : lt.ask;
      const slHit = pos.sl !== null && (pos.side === "buy" ? px <= pos.sl : px >= pos.sl);
      const tpHit = pos.tp !== null && (pos.side === "buy" ? px >= pos.tp : px <= pos.tp);
      if (slHit || tpHit) hits.push({ ...pos, exit: px, pnl: pnl(pos, lt.bid, lt.ask), closed: lt.time, reason: slHit ? "stop loss" : "take profit" });
      else keep.push(pos);
    }
    if (hits.length) update({ ...cur, open: keep, history: [...hits, ...cur.history].slice(0, 200), balance: cur.balance + hits.reduce((a, h) => a + h.pnl, 0) });
  }, [lt?.time, lt?.bid, lt?.ask]); // eslint-disable-line react-hooks/exhaustive-deps

  const latest: Signal | undefined = latestSignals(sig.data, 1).find((s) => s.status === "pending") ?? latestSignals(sig.data, 1)[0];

  if (!p) {
    return (
      <>
        <PageHeader title="Practice" subtitle="Learn to trade gold before risking money." />
        <Setup onStart={(balance, lot) => update({ start: balance, balance, lot, open: [], history: [] })} />
      </>
    );
  }

  const floating = lt ? p.open.reduce((a, pos) => a + pnl(pos, lt.bid, lt.ask), 0) : 0;
  const wins = p.history.filter((h) => h.pnl > 0).length;
  const losses = p.history.filter((h) => h.pnl <= 0).length;

  const open = (side: "buy" | "sell") => {
    if (!lt) return;
    const s = useSig && latest && String(latest.side).toLowerCase() === side ? latest : null;
    const pos: Position = {
      id: Date.now(),
      side,
      lots: p.lot,
      entry: side === "buy" ? lt.ask : lt.bid,
      sl: typeof s?.stop_loss === "number" ? s.stop_loss : null,
      tp: typeof s?.take_profit === "number" ? s.take_profit : null,
      opened: lt.time,
    };
    update({ ...p, open: [pos, ...p.open] });
  };
  const close = (pos: Position) => {
    if (!lt) return;
    const c: Closed = { ...pos, exit: pos.side === "buy" ? lt.bid : lt.ask, pnl: pnl(pos, lt.bid, lt.ask), closed: lt.time, reason: "manual" };
    update({ ...p, open: p.open.filter((x) => x.id !== pos.id), history: [c, ...p.history].slice(0, 200), balance: p.balance + c.pnl });
  };
  const first = p.open[0];

  return (
    <>
      <PageHeader
        title="Practice"
        subtitle="Practice money only. Kept in this browser; not part of the AI's memory."
        actions={
          <button className="btn btn-small" onClick={() => setReset(true)}>
            Reset
          </button>
        }
      />

      <div className="stats stats-3">
        <div className="stat">
          <div className="stat-label">Practice balance</div>
          <div className="stat-value">${fmtNum(p.balance, 2)}</div>
          <div className="stat-hint">started with ${fmtNum(p.start, 2)}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Floating P/L</div>
          <div className={`stat-value ${signClass(floating)}`}>{fmtMoney(floating)}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Win rate</div>
          <div className="stat-value">{p.history.length ? `${Math.round((wins / p.history.length) * 100)}%` : "n/a"}</div>
          <div className="stat-hint">
            {wins} wins · {losses} losses
          </div>
        </div>
      </div>

      <Card title={mkt.data ? `${mkt.data.symbol} live` : "Live price"} actions={lt ? <span className="price-inline">{fmtNum(lt.bid, 2)}</span> : undefined}>
        {ticks.length < 2 ? (
          <Empty>{mkt.error ? `No live price: ${mkt.error}` : `Collecting live ticks... (${ticks.length})`}</Empty>
        ) : (
          <div className="chart" role="img" aria-label="Live bid price">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={ticks} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="t" tickFormatter={(v: string) => new Date(v).toLocaleTimeString()} tick={{ fill: "var(--text-2)", fontSize: 11 }} tickLine={false} minTickGap={50} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--text-2)", fontSize: 11 }} tickLine={false} axisLine={false} width={60} />
                <Tooltip labelFormatter={(v) => fmtTime(String(v))} formatter={(v: number) => [fmtNum(v, 2), "Bid"]} />
                {first && <ReferenceLine y={first.entry} stroke="var(--text-2)" strokeDasharray="4 4" label={{ value: "Entry", fill: "var(--text-2)", fontSize: 10, position: "insideLeft" }} />}
                {first?.sl != null && <ReferenceLine y={first.sl} stroke="var(--neg)" strokeDasharray="4 4" label={{ value: "SL", fill: "var(--neg)", fontSize: 10, position: "insideLeft" }} />}
                {first?.tp != null && <ReferenceLine y={first.tp} stroke="var(--pos)" strokeDasharray="4 4" label={{ value: "TP", fill: "var(--pos)", fontSize: 10, position: "insideLeft" }} />}
                <Line type="linear" dataKey="bid" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        <LotPicker lot={p.lot} setLot={(lot) => update({ ...p, lot })} />
        <div className="trade-btns">
          <button className="btn btn-buy" disabled={!lt} onClick={() => open("buy")}>
            Buy {lt ? fmtNum(lt.ask, 2) : ""}
          </button>
          <button className="btn btn-sell" disabled={!lt} onClick={() => open("sell")}>
            Sell {lt ? fmtNum(lt.bid, 2) : ""}
          </button>
        </div>
        <label className="field inline small">
          <input type="checkbox" checked={useSig} onChange={(e) => setUseSig(e.target.checked)} style={{ width: "auto", minHeight: 0 }} />
          <span>Use the latest signal's SL and TP when trading in its direction</span>
        </label>
        <p className="muted small">P/L assumes {OZ_PER_LOT} oz per lot and the live bid/ask. Stop loss and take profit are checked only while this page is open.</p>
      </Card>

      {latest && (
        <Card title="Latest AI signal">
          <SignalCard s={latest} />
        </Card>
      )}

      <Card title={`Open practice trades (${p.open.length})`}>
        {p.open.length ? (
          <div className="pos-list">
            {p.open.map((pos) => {
              const v = lt ? pnl(pos, lt.bid, lt.ask) : null;
              return (
                <div className="pos" key={pos.id}>
                  <span className={`signal-side ${pos.side}`}>{pos.side.toUpperCase()}</span>
                  <span className="mono small">
                    {pos.lots.toFixed(2)} @ {fmtNum(pos.entry, 2)}
                    {pos.sl !== null ? ` · SL ${fmtNum(pos.sl, 2)}` : ""}
                    {pos.tp !== null ? ` · TP ${fmtNum(pos.tp, 2)}` : ""}
                  </span>
                  <b className={signClass(v)}>{v === null ? "n/a" : fmtMoney(v)}</b>
                  <button className="btn btn-small" onClick={() => close(pos)} disabled={!lt}>
                    Close
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <Empty>No open practice trades.</Empty>
        )}
      </Card>

      {p.history.length > 0 && (
        <Card title="Practice history">
          <div className="pos-list">
            {p.history.slice(0, 20).map((h) => (
              <div className="pos" key={h.id}>
                <span className={`signal-side ${h.side}`}>{h.side.toUpperCase()}</span>
                <span className="mono small">
                  {fmtNum(h.entry, 2)} → {fmtNum(h.exit, 2)} · {h.reason}
                </span>
                <b className={signClass(h.pnl)}>{fmtMoney(h.pnl)}</b>
                <span className="muted small">{fmtTime(h.closed)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <ConfirmDialog
        open={reset}
        title="Reset practice?"
        confirmLabel="Reset"
        body={<p>Clears the practice balance, open trades and history in this browser.</p>}
        onConfirm={async () => update(null)}
        onClose={() => setReset(false)}
      />
    </>
  );
}
