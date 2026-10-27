import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { api, type ProfitAlert } from "../api";
import { fmtMoney, fmtNum, fmtTime } from "../lib";
import { nativeApp } from "../native";
import { Icon } from "./icons";

/**
 * In-app alerts for trades that closed in profit (virtual or real, always labelled).
 * Polls the server's recorded trades; it shows nothing the engines did not record and never acts on a trade.
 */
const POLL_MS = 15000;
const TOAST_MS = 12000;
const READ_KEY = "gold_ai.profit_alerts.read";

function load(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private window: alerts still work, only "read" is forgotten */
  }
}

function tag(a: ProfitAlert): string {
  return a.simulated ? "VIRTUAL" : "REAL";
}

export function profitTitle(a: ProfitAlert): string {
  return `${tag(a)} ${a.style_label} ${a.side} ${a.symbol} closed in profit`;
}

export function profitText(a: ProfitAlert): string {
  const pips = a.pips !== null ? ` · ${a.pips > 0 ? "+" : ""}${fmtNum(a.pips, 1)} pips` : "";
  return `${fmtMoney(a.net_pnl)}${pips} · ${fmtNum(a.entry_price, a.digits)} → ${fmtNum(a.exit_price, a.digits)}${a.exploration ? " · exploration" : ""}`;
}

function browserNotify(a: ProfitAlert) {
  // The Android app posts its own notification from its background service; avoid a duplicate.
  if (nativeApp.available() || typeof Notification === "undefined" || Notification.permission !== "granted") return;
  try {
    new Notification(profitTitle(a), { body: profitText(a), tag: a.id });
  } catch {
    /* some browsers only allow notifications from a service worker */
  }
}

function AlertRow({ a }: { a: ProfitAlert }) {
  return (
    <>
      <div className="palert-head">
        <span className={`pill ${a.simulated ? "pill-info" : "pill-ok"}`}>{tag(a)}</span>
        <strong>
          {a.style_label} {a.side} {a.symbol}
        </strong>
        <span className="pos mono">{fmtMoney(a.net_pnl)}</span>
      </div>
      <div className="small muted">
        {profitText(a)} · {fmtTime(a.exit_time)}
      </div>
    </>
  );
}

export default function ProfitAlerts() {
  const nav = useNavigate();
  const [alerts, setAlerts] = useState<ProfitAlert[]>([]);
  const [toasts, setToasts] = useState<ProfitAlert[]>([]);
  const [open, setOpen] = useState(false);
  const [readAt, setReadAt] = useState<string>(() => load(READ_KEY) ?? "");
  const seen = useRef<Set<string> | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const poll = useCallback(() => {
    api
      .profitCloses(30)
      .then((list) => {
        setAlerts(list);
        // The first load only remembers what is already there, so old closes don't all pop up at once.
        if (seen.current === null) {
          seen.current = new Set(list.map((a) => a.id));
          return;
        }
        const fresh = list.filter((a) => !seen.current!.has(a.id));
        fresh.forEach((a) => seen.current!.add(a.id));
        if (!fresh.length) return;
        setToasts((t) => [...fresh.slice(0, 3), ...t].slice(0, 3));
        fresh.slice(0, 3).forEach(browserNotify);
      })
      .catch(() => {
        /* an older server has no alert endpoint; the bell stays empty */
      });
  }, []);

  useEffect(() => {
    poll();
    const t = window.setInterval(poll, POLL_MS);
    return () => window.clearInterval(t);
  }, [poll]);

  useEffect(() => {
    if (!toasts.length) return;
    const t = window.setTimeout(() => setToasts((x) => x.slice(0, -1)), TOAST_MS);
    return () => window.clearTimeout(t);
  }, [toasts]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const unread = alerts.filter((a) => a.exit_time > readAt).length;

  const toggle = () => {
    setOpen((o) => !o);
    if (!open && alerts.length) {
      setReadAt(alerts[0].exit_time);
      save(READ_KEY, alerts[0].exit_time);
    }
  };

  const goResults = () => {
    setOpen(false);
    setToasts([]);
    nav("/results");
  };

  const canAsk = !nativeApp.available() && typeof Notification !== "undefined" && Notification.permission === "default";

  return (
    <div className="palert" ref={box}>
      <button className="btn btn-icon palert-btn" onClick={toggle} aria-label={`Profit alerts${unread ? `, ${unread} new` : ""}`} aria-expanded={open} title="Trades closed in profit">
        <Icon name="bell" />
        {unread > 0 && <span className="palert-badge">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="palert-panel" role="dialog" aria-label="Trades closed in profit">
          <div className="palert-panel-head">
            <strong>Closed in profit</strong>
            <span className="small muted">Virtual = estimated fills</span>
          </div>
          {alerts.length === 0 ? (
            <div className="small muted palert-empty">No profitable closes recorded yet.</div>
          ) : (
            <ul className="palert-list">
              {alerts.slice(0, 10).map((a) => (
                <li key={a.id}>
                  <button className="palert-item" onClick={goResults}>
                    <AlertRow a={a} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {canAsk && (
            <button className="btn btn-small btn-ghost palert-ask" onClick={() => Notification.requestPermission().catch(() => undefined)}>
              Also show browser notifications
            </button>
          )}
        </div>
      )}
      {/* The header's backdrop blur would trap fixed toasts inside it, so they render on the page body. */}
      {createPortal(
        <div className="palert-toasts" aria-live="polite">
          {toasts.map((a) => (
            <div key={a.id} className="palert-toast" role="status">
              <button className="palert-item" onClick={goResults}>
                <AlertRow a={a} />
              </button>
              <button className="btn btn-icon btn-ghost palert-x" aria-label="Dismiss" onClick={() => setToasts((t) => t.filter((x) => x.id !== a.id))}>
                ×
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </div>
  );
}
