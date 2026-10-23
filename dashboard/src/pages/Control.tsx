import { useState, type FormEvent } from "react";
import { latestSignals, SignalCard, signalTime } from "../components/SignalCard";
import { canonical, instrumentChoices, priceDigits, SymbolChips, useInstruments } from "../instruments";
import { api, type Signal, type SignalAction } from "../api";
import { Card, ConfirmDialog, DataView, ErrorState, JsonBlock, KVTable, PageHeader, Pill, Stat, Table, toneFor } from "../components/ui";
import { fmtNum, fmtTime, humanize, useApi } from "../lib";
import { useAuth, useLive } from "../state";

// ---------------------------------------------------------------- risk

export function RiskPage() {
  const st = useApi(api.risk, [], 15000);
  const { overview, refresh } = useLive();
  const [dlg, setDlg] = useState(false);
  return (
    <>
      <PageHeader title="Risk Management" subtitle="Hard limits enforced by the risk engine before any order, virtual or real." />
      <Card title="Emergency stop" badge={overview ? <Pill tone={overview.emergency_stop ? "bad" : "ok"}>{overview.emergency_stop ? "ACTIVE" : "inactive"}</Pill> : undefined}>
        <p className="small">The emergency stop button is also available in the top banner on every page.</p>
        <button className="btn btn-danger" onClick={() => setDlg(true)}>
          Activate emergency stop
        </button>
      </Card>
      <DataView state={st}>
        {(r) => (
          <div className="grid-2">
            <Card title="Configured limits">
              <KVTable data={r.config} emptyText="No risk configuration reported." />
            </Card>
            <Card title="Current risk state">
              <KVTable data={r.state} emptyText="No risk state reported." />
            </Card>
          </div>
        )}
      </DataView>
      <ConfirmDialog
        open={dlg}
        title="Activate emergency stop?"
        danger
        withReason
        confirmLabel="Activate emergency stop"
        body={<p>Halts new entries on every engine. Audited.</p>}
        onConfirm={async (reason) => {
          await api.emergencyStop(true, reason || "risk page emergency stop");
          refresh();
          st.reload();
        }}
        onClose={() => setDlg(false)}
      />
    </>
  );
}

// ---------------------------------------------------------------- modes

export function ModesPage() {
  const { overview, overviewError, auth } = useLive();
  const settings = useApi(api.settings, []);
  const modeSettings = settings.data ? Object.fromEntries(Object.entries(settings.data).filter(([k]) => /mode|enabled|demo|virtual|real|approval/i.test(k))) : null;
  return (
    <>
      <PageHeader title="Trading Modes" subtitle="Which execution paths are currently switched on, as reported by the backend." />
      {!overview && overviewError && <ErrorState error={overviewError} />}
      {overview && (
        <Card title="Execution paths">
          <Table
            rows={[
              { mode: "Live virtual (paper, estimated fills)", on: (overview.virtual_engines ?? []).length > 0, detail: `${(overview.virtual_engines ?? []).length} engine(s) running` },
              { mode: "Demo account execution", on: overview.demo_execution_enabled, detail: "Orders on broker demo accounts" },
              {
                mode: "Real money execution",
                on: auth?.real_trading_enabled ?? overview.real_trading_enabled,
                detail: auth?.grant?.expires_at ? `Grant expires ${fmtTime(auth.grant.expires_at)}` : "Requires owner grant",
              },
              { mode: "Emergency stop", on: overview.emergency_stop, detail: "Blocks all new entries when on" },
            ]}
            rowKey={(r) => r.mode}
            columns={[
              { key: "mode", label: "Mode" },
              { key: "on", label: "State", render: (r) => <Pill tone={r.mode.startsWith("Real") || r.mode.startsWith("Emergency") ? (r.on ? "bad" : "ok") : r.on ? "ok" : "neutral"}>{r.on ? "ON" : "OFF"}</Pill> },
              { key: "detail", label: "Detail" },
            ]}
          />
        </Card>
      )}
      <Card title="Mode-related settings">
        <DataView state={settings}>{() => <KVTable data={modeSettings} emptyText="No mode-related settings reported." />}</DataView>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- signals

export function SignalsPage() {
  const all = useApi(api.signals, [], 10000);
  const running = useInstruments(60000);
  const [sym, setSym] = useState<string | null>(null);
  const choices = instrumentChoices(running.data, (all.data ?? []).map((x) => x.symbol));
  const st = { ...all, data: all.data ? all.data.filter((x) => sym === null || canonical(x.symbol) === sym) : null };
  const [act, setAct] = useState<{ s: Signal; a: SignalAction } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Signals and Notifications" subtitle="Trade signals proposed by the agent. Actions are sent with the signal's one-time action token." actions={<button className="btn" onClick={st.reload}>Refresh</button>} />
      {msg && <p className="state state-ok">{msg}</p>}
      <SymbolChips choices={choices} value={sym} onChange={setSym} allLabel="All markets" />
      {st.data && st.data.some((s) => s.status === "pending") && (
        <div className="signal-list">
          {latestSignals(st.data.filter((s) => s.status === "pending"), 4).map((s) => (
            <SignalCard key={String(s.id)} s={s} />
          ))}
        </div>
      )}
      <Card title="Signals">
        <DataView state={st} isEmpty={(d) => !d.length} empty="No signals yet.">
          {(rows) => (
            <Table
              rows={rows}
              rowKey={(r, i) => String(r.id ?? i)}
              columns={[
                { key: "time", label: "Time", render: (r) => fmtTime(signalTime(r)) },
                { key: "domain", label: "Domain", render: (r) => r.domain ?? "n/a" },
                { key: "broker", label: "Broker" },
                { key: "symbol", label: "Symbol", render: (r) => r.symbol ?? "n/a" },
                { key: "side", label: "Side", render: (r) => <span className={`side side-${String(r.side ?? "").toLowerCase()}`}>{r.side ?? "n/a"}</span> },
                { key: "confidence", label: "Conf.", className: "num", render: (r) => fmtNum(r.confidence, 2) },
                { key: "entry", label: "Entry", className: "num", render: (r) => fmtNum(r.entry, typeof r.digits === "number" ? r.digits : priceDigits(r.symbol)) },
                { key: "stop_loss", label: "SL", className: "num", render: (r) => fmtNum(r.stop_loss, typeof r.digits === "number" ? r.digits : priceDigits(r.symbol)) },
                { key: "take_profit", label: "TP", className: "num", render: (r) => fmtNum(r.take_profit, typeof r.digits === "number" ? r.digits : priceDigits(r.symbol)) },
                { key: "lots", label: "Lots", className: "num", render: (r) => fmtNum(r.suggested_lots ?? r.lots, 2) },
                { key: "status", label: "Status", render: (r) => <Pill tone={toneFor(r.status)}>{r.status ?? "n/a"}</Pill> },
                { key: "explanation", label: "Why", render: (r) => <span className="small">{r.reason ?? r.explanation ?? ""}</span> },
                {
                  key: "actions",
                  label: "Action",
                  render: (r) => {
                    const tok = r.action_token ?? r.token;
                    if (!tok) return <span className="muted small">no action token</span>;
                    return (
                      <div className="row-actions">
                        {(["approve", "reject", "ignore", "manual"] as SignalAction[]).map((a) => (
                          <button key={a} className={`btn btn-small ${a === "approve" ? "btn-primary" : ""}`} onClick={() => setAct({ s: r, a })}>
                            {humanize(a)}
                          </button>
                        ))}
                      </div>
                    );
                  },
                },
              ]}
            />
          )}
        </DataView>
      </Card>
      <ConfirmDialog
        open={act !== null}
        title={act ? `${humanize(act.a)} signal ${act.s.id}?` : ""}
        confirmLabel={act ? humanize(act.a) : "OK"}
        danger={act?.a === "approve"}
        body={<p>The backend re-checks risk limits, news blackout, emergency stop and authorization before acting. Approving does not bypass any of them.</p>}
        onConfirm={async () => {
          if (!act) return;
          const r = await api.signalAction(act.s.id, act.a, (act.s.action_token ?? act.s.token) as string);
          setMsg(`Signal ${act.s.id}: ${act.a} -> ${JSON.stringify(r)}`);
          st.reload();
        }}
        onClose={() => setAct(null)}
      />
    </>
  );
}

// ---------------------------------------------------------------- owner authorization

export const AUTH_PHRASE = "I AUTHORIZE REAL MONEY TRADING";

export function AuthorizationPage() {
  const { auth, authError, refresh } = useLive();
  const { role } = useAuth();
  const [password, setPassword] = useState("");
  const [phrase, setPhrase] = useState("");
  const [accounts, setAccounts] = useState("");
  const [maxLots, setMaxLots] = useState("");
  const [hours, setHours] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [revoke, setRevoke] = useState(false);

  const accList = accounts
    .split(/[\s,]+/)
    .map((a) => a.trim())
    .filter(Boolean);
  const lots = Number(maxLots);
  const hrs = Number(hours);
  const valid = phrase === AUTH_PHRASE && password.length > 0 && accList.length > 0 && maxLots !== "" && lots > 0 && hours !== "" && hrs > 0;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setErr(null);
    setOk(null);
    try {
      const r = await api.grant({ password, phrase, accounts: accList, max_lots: lots, hours: hrs });
      setOk(`Grant accepted by backend: ${JSON.stringify(r)}`);
      setPassword("");
      setPhrase("");
      refresh();
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Owner Authorization" subtitle="The only way real-money trading can be switched on." />
      <Card title="Important">
        <ul className="small">
          <li>
            <strong>A maturity score never enables trading.</strong> Passing every maturity gate only means the evidence threshold was met; it does not authorize anything.
          </li>
          <li>Real trading requires this explicit, time-limited owner grant, restricted to the listed accounts and a maximum lot size.</li>
          <li>The backend re-verifies your password, the exact phrase, the account allowlist and all risk limits. Every grant and revoke is audited.</li>
          <li>The emergency stop overrides any grant.</li>
        </ul>
      </Card>
      <Card title="Current state">
        {auth ? (
          <>
            <div className="stats">
              <Stat label="Real trading" value={auth.real_trading_enabled ? "ENABLED" : "DISABLED"} tone={auth.real_trading_enabled ? "neg" : ""} />
              <Stat label="Grant expires" value={auth.grant?.expires_at ? fmtTime(auth.grant.expires_at) : "no active grant"} />
              <Stat label="Account allowlist" value={auth.account_allowlist?.length ? auth.account_allowlist.join(", ") : "empty"} />
            </div>
            {auth.grant && (
              <>
                <JsonBlock value={auth.grant} />
                <button className="btn btn-danger" onClick={() => setRevoke(true)}>
                  Revoke grant now
                </button>
              </>
            )}
          </>
        ) : authError ? (
          <ErrorState error={authError} />
        ) : (
          <div className="state state-loading">Loading...</div>
        )}
      </Card>
      <Card title="Grant real-money authorization">
        {role && role !== "owner" && <p className="state state-warn">You are signed in as "{role}". The backend will likely reject this unless you are the owner.</p>}
        <form className="form" onSubmit={submit} autoComplete="off">
          <label className="field field-wide">
            <span>
              Type exactly: <code>{AUTH_PHRASE}</code>
            </span>
            <input value={phrase} onChange={(e) => setPhrase(e.target.value)} autoComplete="off" spellCheck={false} />
            {phrase && phrase !== AUTH_PHRASE && <small className="neg">Phrase does not match exactly.</small>}
          </label>
          <label className="field">
            <span>Owner password</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </label>
          <label className="field">
            <span>Accounts (comma or space separated)</span>
            <input value={accounts} onChange={(e) => setAccounts(e.target.value)} placeholder="e.g. 12345678" />
          </label>
          <label className="field">
            <span>Max lots per order</span>
            <input type="number" step="0.01" min="0.01" value={maxLots} onChange={(e) => setMaxLots(e.target.value)} />
          </label>
          <label className="field">
            <span>Duration (hours)</span>
            <input type="number" step="1" min="1" value={hours} onChange={(e) => setHours(e.target.value)} />
          </label>
          {err && <div className="field-wide"><ErrorState error={err} /></div>}
          {ok && <p className="state state-ok field-wide">{ok}</p>}
          <div className="field-wide">
            <button className="btn btn-danger" disabled={!valid || busy}>
              {busy ? "Submitting..." : "Grant real-money authorization"}
            </button>
          </div>
        </form>
      </Card>
      <ConfirmDialog
        open={revoke}
        title="Revoke real-money authorization?"
        danger
        confirmLabel="Revoke"
        body={<p>Real trading will be disabled immediately.</p>}
        onConfirm={async () => {
          await api.revoke();
          refresh();
        }}
        onClose={() => setRevoke(false)}
      />
    </>
  );
}
