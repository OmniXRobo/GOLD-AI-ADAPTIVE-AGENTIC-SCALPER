import { useMemo, useState } from "react";
import { api } from "../api";
import { Card, ConfirmDialog, DataView, JsonBlock, KVTable, PageHeader, Pill, Stat, Table, toneFor } from "../components/ui";
import { nativeApp } from "../native";
import { fmtTime, useApi } from "../lib";

export function HealthPage() {
  const sys = useApi(api.systemHealth, [], 15000);
  const ping = useApi(api.health, [], 15000);
  return (
    <>
      <PageHeader title="System Health" subtitle="Backend self-checks, refreshed every 15 s." />
      <Card title="API liveness (/api/health)">
        <DataView state={ping}>{(h) => <KVTable data={h} />}</DataView>
      </Card>
      <Card title="System checks">
        <DataView state={sys}>
          {(s) => (
            <>
              <p>
                Overall: <Pill tone={toneFor(s.overall)}>{s.overall}</Pill>
              </p>
              <Table
                rows={s.checks ?? []}
                rowKey={(c) => c.name}
                empty="No checks reported."
                columns={[
                  { key: "name", label: "Check" },
                  { key: "status", label: "Status", render: (c) => <Pill tone={toneFor(c.status)}>{c.status}</Pill> },
                  { key: "detail", label: "Detail", render: (c) => <span className="small">{c.detail ?? ""}</span> },
                ]}
              />
            </>
          )}
        </DataView>
      </Card>
    </>
  );
}

export function SettingsPage() {
  const st = useApi(api.settings, []);
  return (
    <>
      <PageHeader title="Settings" subtitle="Effective backend configuration (read-only; secrets should be redacted by the backend)." />
      <MobileAppCard />
      <Card title="Configuration">
        <DataView state={st} isEmpty={(d) => !Object.keys(d).length}>
          {(d) => <KVTable data={d} />}
        </DataView>
      </Card>
    </>
  );
}

function MobileAppCard() {
  const [dlg, setDlg] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const inApp = nativeApp.available();
  return (
    <Card title="Android app">
      {inApp ? (
        <div className="stats">
          <Stat label="App version" value={nativeApp.version() ?? "n/a"} />
          <Stat label="Signal alerts" value={nativeApp.alertsEnabled() ? "on" : "off"} hint="Read-only alerts for new signals" />
        </div>
      ) : (
        <p className="muted small">
          Install the Android app from the repository's <code>android/</code> folder to view this dashboard on your phone and receive signal alerts. See <code>docs/ANDROID_APP.md</code>.
        </p>
      )}
      <div className="page-actions" style={{ marginTop: 12 }}>
        {inApp && (
          <button className="btn" onClick={() => nativeApp.openSettings()}>
            Server and alert settings
          </button>
        )}
        <button className="btn" onClick={() => setDlg(true)}>
          Revoke all phone alert tokens
        </button>
        {done && <span className="small muted">{done}</span>}
      </div>
      <ConfirmDialog
        open={dlg}
        title="Revoke all phone alert tokens?"
        confirmLabel="Revoke"
        body={<p>Every phone stops receiving signal alerts until someone signs in on it again. Requires the admin permission. The action is audited.</p>}
        onConfirm={async () => {
          await api.revokeDeviceTokens();
          setDone("All phone alert tokens revoked.");
        }}
        onClose={() => setDlg(false)}
      />
    </Card>
  );
}

export function AuditPage() {
  const [limit, setLimit] = useState(200);
  const st = useApi(() => api.audit(limit), [limit]);
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const all = st.data ?? [];
    const s = q.trim().toLowerCase();
    return s ? all.filter((a) => `${a.actor} ${a.action} ${JSON.stringify(a.detail)}`.toLowerCase().includes(s)) : all;
  }, [st.data, q]);
  return (
    <>
      <PageHeader
        title="Audit Logs"
        subtitle="Append-only record of privileged actions."
        actions={
          <>
            <input className="search" placeholder="Filter" value={q} onChange={(e) => setQ(e.target.value)} />
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[50, 200, 500, 1000].map((n) => (
                <option key={n} value={n}>
                  last {n}
                </option>
              ))}
            </select>
            <button className="btn" onClick={st.reload}>
              Refresh
            </button>
          </>
        }
      />
      <Card title={`Entries${st.data ? ` (${rows.length}${q ? ` of ${st.data.length}` : ""})` : ""}`}>
        <DataView state={st} isEmpty={(d) => !d.length} empty="No audit entries yet.">
          {() => (
            <Table
              rows={rows}
              rowKey={(a, i) => `${a.time}-${i}`}
              empty="No entries match the filter."
              columns={[
                { key: "time", label: "Time", render: (a) => fmtTime(a.time) },
                { key: "actor", label: "Actor" },
                { key: "action", label: "Action", render: (a) => <span className="mono">{a.action}</span> },
                { key: "detail", label: "Detail", render: (a) => <code className="small wrap">{JSON.stringify(a.detail)}</code> },
              ]}
            />
          )}
        </DataView>
      </Card>
    </>
  );
}

export function BackupsPage() {
  const st = useApi(api.backups, []);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <>
      <PageHeader
        title="Backup and Recovery"
        subtitle="Database snapshots created by the backend."
        actions={
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setMsg(null);
              try {
                const b = await api.createBackup();
                setMsg({ ok: true, text: `Backup created: ${b.name ?? b.path ?? JSON.stringify(b)}` });
                st.reload();
              } catch (e) {
                setMsg({ ok: false, text: (e as Error).message });
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Creating..." : "Create backup now"}
          </button>
        }
      />
      {msg && <p className={`state ${msg.ok ? "state-ok" : "state-error"}`}>{msg.text}</p>}
      <Card title="Backups">
        <DataView state={st} isEmpty={(d) => !d.length} empty="No backups yet.">
          {(rows) => (
            <Table
              rows={rows}
              rowKey={(b, i) => String(b.name ?? b.path ?? i)}
              columns={[
                { key: "name", label: "Name", render: (b) => <span className="mono small">{b.name ?? b.path ?? "n/a"}</span> },
                { key: "created_at", label: "Created", render: (b) => fmtTime(b.created_at) },
                { key: "size_bytes", label: "Size", className: "num", render: (b) => (typeof b.size_bytes === "number" ? `${(b.size_bytes / 1048576).toFixed(2)} MB` : "n/a") },
              ]}
            />
          )}
        </DataView>
      </Card>
      <Card title="Recovery">
        <p className="small">The API exposes no restore endpoint. Restoring a snapshot is an offline operator task: stop the backend, replace the database file with the chosen backup, then start the backend again and verify System Health and memory counts.</p>
        {st.data && st.data.length > 0 && (
          <details>
            <summary>Raw backup list</summary>
            <JsonBlock value={st.data} />
          </details>
        )}
      </Card>
    </>
  );
}
