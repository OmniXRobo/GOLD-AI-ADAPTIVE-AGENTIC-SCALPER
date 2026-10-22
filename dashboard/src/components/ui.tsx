import { useEffect, useRef, useState, type ReactNode } from "react";
import { DOMAIN_BADGE, type Domain } from "../api";
import type { ApiState } from "../lib";
import { fmtValue, humanize } from "../lib";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Card({ title, badge, actions, children, className }: { title?: ReactNode; badge?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || badge || actions) && (
        <div className="card-head">
          <div className="card-title">
            {title && <h2>{title}</h2>}
            {badge}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function DomainBadge({ domain }: { domain: Domain }) {
  return <span className={`badge domain-${domain}`}>{DOMAIN_BADGE[domain]}</span>;
}

export type Tone = "ok" | "warn" | "bad" | "neutral" | "info";

export function Pill({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

export function toneFor(status: string | boolean | null | undefined): Tone {
  if (typeof status === "boolean") return status ? "ok" : "bad";
  const s = (status ?? "").toLowerCase();
  if (["ok", "pass", "passed", "healthy", "up", "connected", "green", "true"].includes(s)) return "ok";
  if (["warn", "warning", "degraded", "stale", "insufficient_data", "yellow"].includes(s)) return "warn";
  if (["fail", "failed", "error", "down", "critical", "red", "false", "disconnected"].includes(s)) return "bad";
  return "neutral";
}

export function Empty({ children = "No data yet" }: { children?: ReactNode }) {
  return <div className="state state-empty">{children}</div>;
}

export function ErrorState({ error }: { error: string }) {
  return (
    <div className="state state-error" role="alert">
      <strong>Endpoint unavailable</strong>
      <span className="mono small">{error}</span>
    </div>
  );
}

/** Renders loading / error / empty states; children only receive real data. */
export function DataView<T>({ state, isEmpty, empty, children }: { state: ApiState<T>; isEmpty?: (d: T) => boolean; empty?: ReactNode; children: (d: T) => ReactNode }) {
  if (state.error) return <ErrorState error={state.error} />;
  if (state.data === null) return state.loading ? <div className="state state-loading">Loading...</div> : <Empty />;
  if (isEmpty?.(state.data)) return <Empty>{empty ?? "No data yet"}</Empty>;
  return <>{children(state.data)}</>;
}

export function Stat({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: string; hint?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone ?? ""}`}>{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function KVTable({ data, emptyText }: { data: Record<string, unknown> | null | undefined; emptyText?: string }) {
  const entries = Object.entries(data ?? {});
  if (!entries.length) return <Empty>{emptyText ?? "No data yet"}</Empty>;
  return (
    <div className="table-wrap">
      <table className="kv">
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <th>{humanize(k)}</th>
              <td className="mono">{v !== null && typeof v === "object" ? <pre className="json">{JSON.stringify(v, null, 2)}</pre> : fmtValue(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  className?: string;
}

export function Table<T>({ rows, columns, rowKey, empty }: { rows: T[]; columns: Column<T>[]; rowKey: (r: T, i: number) => string; empty?: ReactNode }) {
  if (!rows.length) return <Empty>{empty ?? "No data yet"}</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.className}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey(r, i)}>
              {columns.map((c) => (
                <td key={c.key} className={c.className} data-label={c.label}>
                  {c.render ? c.render(r) : fmtValue((r as Record<string, unknown>)[c.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Modal confirmation. `requireText` forces the user to type an exact string. */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  danger,
  requireText,
  withReason,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  requireText?: string;
  withReason?: boolean;
  onConfirm: (reason: string) => Promise<void> | void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      setText("");
      setReason("");
      setErr(null);
      d.showModal();
    } else if (!open && d.open) d.close();
  }, [open]);

  const ok = !busy && (!requireText || text === requireText);
  return (
    <dialog ref={ref} className="dialog" onClose={onClose} onCancel={onClose}>
      <form
        method="dialog"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!ok) return;
          setBusy(true);
          setErr(null);
          try {
            await onConfirm(reason);
            onClose();
          } catch (ex) {
            setErr((ex as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <h2>{title}</h2>
        <div className="dialog-body">{body}</div>
        {withReason && (
          <label className="field">
            <span>Reason (recorded in audit log)</span>
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. abnormal spread" />
          </label>
        )}
        {requireText && (
          <label className="field">
            <span>
              Type <code>{requireText}</code> to confirm
            </span>
            <input value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" />
          </label>
        )}
        {err && <ErrorState error={err} />}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className={`btn ${danger ? "btn-danger" : "btn-primary"}`} disabled={!ok}>
            {busy ? "Working..." : confirmLabel}
          </button>
        </div>
      </form>
    </dialog>
  );
}

export function JsonBlock({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <Empty />;
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}
