import { useState } from "react";
import { Link } from "react-router-dom";
import { Card, PageHeader } from "../components/ui";
import { fmtNum, humanize } from "../lib";
import { FAQ, HOW, MONEY } from "../content";
import { GOLD_PIP } from "../results";

type Tab = "how" | "calculator" | "money" | "faq";
const OZ_PER_LOT = 100;

function NumField({ label, value, onChange, step = 1, suffix }: { label: string; value: number; onChange: (n: number) => void; step?: number; suffix?: string }) {
  return (
    <label className="field">
      <span>
        {label}
        {suffix ? ` (${suffix})` : ""}
      </span>
      <input type="number" inputMode="decimal" step={step} min={0} value={Number.isFinite(value) ? value : ""} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

export function Calculator() {
  const [balance, setBalance] = useState(1000);
  const [riskPct, setRiskPct] = useState(1);
  const [slPips, setSlPips] = useState(50);
  const [rr, setRr] = useState(1.5);
  const riskMoney = (balance * riskPct) / 100;
  const pipValuePerLot = GOLD_PIP * OZ_PER_LOT; // $ per pip for 1.00 lot
  const rawLots = slPips > 0 ? riskMoney / (slPips * pipValuePerLot) : 0;
  const lots = Math.floor(rawLots * 100) / 100;
  const actualRisk = lots * slPips * pipValuePerLot;
  return (
    <Card title="Lot size and risk calculator">
      <div className="form">
        <NumField label="Account balance" suffix="USD" value={balance} onChange={setBalance} step={100} />
        <NumField label="Risk per trade" suffix="%" value={riskPct} onChange={setRiskPct} step={0.25} />
        <NumField label="Stop loss distance" suffix="pips" value={slPips} onChange={setSlPips} step={5} />
        <NumField label="Reward to risk" suffix="R" value={rr} onChange={setRr} step={0.1} />
      </div>
      <div className="stats" style={{ marginTop: 14 }}>
        <div className="stat">
          <div className="stat-label">Lot size</div>
          <div className="stat-value">{lots >= 0.01 ? lots.toFixed(2) : "below 0.01"}</div>
          <div className="stat-hint">rounded down to 0.01</div>
        </div>
        <div className="stat">
          <div className="stat-label">Money at risk</div>
          <div className="stat-value">${fmtNum(lots >= 0.01 ? actualRisk : riskMoney, 2)}</div>
          <div className="stat-hint">if the stop loss is hit</div>
        </div>
        <div className="stat">
          <div className="stat-label">Target profit</div>
          <div className="stat-value pos">${fmtNum((lots >= 0.01 ? actualRisk : riskMoney) * rr, 2)}</div>
          <div className="stat-hint">take profit at {fmtNum(slPips * rr, 0)} pips</div>
        </div>
        <div className="stat">
          <div className="stat-label">Value of 1 pip</div>
          <div className="stat-value">${fmtNum(lots * pipValuePerLot, 2)}</div>
          <div className="stat-hint">${fmtNum(pipValuePerLot, 0)} per pip per 1.00 lot</div>
        </div>
      </div>
      {lots < 0.01 && <p className="state state-warn">This stop is too wide for this balance and risk: even 0.01 lot would risk ${fmtNum(0.01 * slPips * pipValuePerLot, 2)}. Use a tighter stop or skip the trade.</p>}
      <p className="muted small">
        Assumes {OZ_PER_LOT} oz per lot and 1 pip = ${GOLD_PIP.toFixed(2)}. Check your broker's contract size. Spread, commission and slippage add to the real cost.
      </p>
    </Card>
  );
}

function Steps() {
  return (
    <Card title="How it works">
      <ol className="steps">
        {HOW.map(([t, d], i) => (
          <li key={t}>
            <span className="step-n">{i + 1}</span>
            <div>
              <b>{t}</b>
              <p className="muted small">{d}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="small">
        <Link to="/analysis">Open Analysis</Link> · <Link to="/results">See results</Link> · <Link to="/practice">Practice</Link>
      </p>
    </Card>
  );
}

function List({ title, items }: { title: string; items: string[][] }) {
  return (
    <Card title={title}>
      <div className="faq">
        {items.map(([q, a]) => (
          <details key={q}>
            <summary>{q}</summary>
            <p>{a}</p>
          </details>
        ))}
      </div>
    </Card>
  );
}

export default function LearnPage() {
  const [tab, setTab] = useState<Tab>("how");
  return (
    <>
      <PageHeader title="Learn" subtitle="How the platform works, sizing your trades, and common questions." />
      <div className="tabs" role="tablist">
        {(["how", "calculator", "money", "faq"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t === "how" ? "How it works" : t === "faq" ? "FAQ" : t === "money" ? "Money" : humanize(t)}
          </button>
        ))}
      </div>
      {tab === "how" && <Steps />}
      {tab === "calculator" && <Calculator />}
      {tab === "money" && <List title="Money management" items={MONEY} />}
      {tab === "faq" && <List title="Frequently asked questions" items={FAQ} />}
    </>
  );
}

