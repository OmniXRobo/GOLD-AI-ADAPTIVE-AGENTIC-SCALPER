import { useCallback, useEffect, useRef, useState } from "react";
import type { Num } from "./api";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Fetches on mount (and when deps change), optionally polling. Never substitutes data on failure. */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = [], refreshMs?: number): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const seq = useRef(0);
  const inFlight = useRef(false);

  const load = useCallback(() => {
    const id = ++seq.current;
    inFlight.current = true;
    setLoading(true);
    fnRef
      .current()
      .then((d) => {
        if (id !== seq.current) return;
        setData(d);
        setError(null);
      })
      .catch((e: Error) => {
        if (id !== seq.current) return;
        setData(null);
        setError(e.message || "Request failed");
      })
      .finally(() => {
        if (id !== seq.current) return;
        inFlight.current = false;
        setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    load();
    if (!refreshMs) return;
    // Skip a poll while the previous one is still running or the screen is hidden, so a slow server does not
    // get a growing pile of the same request (each one also blocks a browser connection).
    const t = window.setInterval(() => {
      if (!inFlight.current && !document.hidden) load();
    }, refreshMs);
    return () => window.clearInterval(t);
  }, [load, refreshMs]);

  return { data, error, loading, reload: load };
}

/** Returns a finite number or null. "inf" stays a string handled by fmtPF. */
export function finite(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function fmtNum(v: unknown, digits = 2): string {
  const n = finite(v);
  return n === null ? "n/a" : n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtMoney(v: unknown): string {
  const n = finite(v);
  if (n === null) return "n/a";
  const s = Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? "-" : n > 0 ? "+" : ""}${s}`;
}

export function fmtPct(v: unknown, digits = 1): string {
  const n = finite(v);
  return n === null ? "n/a" : `${(n * 100).toFixed(digits)}%`;
}

export function fmtPF(v: Num | undefined): string {
  if (v === "inf") return "inf (no losses)";
  return fmtNum(v, 2);
}

export function fmtTime(v: unknown): string {
  if (typeof v !== "string" || !v) return "n/a";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtDuration(fromIso: unknown, to: Date = new Date()): string {
  if (typeof fromIso !== "string" || !fromIso) return "n/a";
  const from = new Date(fromIso);
  if (Number.isNaN(from.getTime())) return "n/a";
  let s = Math.max(0, Math.floor((to.getTime() - from.getTime()) / 1000));
  const d = Math.floor(s / 86400);
  s -= d * 86400;
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  return d > 0 ? `${d}d ${h}h ${m}m` : h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return "n/a";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : fmtNum(v, 4);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

export function signClass(v: unknown): string {
  const n = finite(v);
  return n === null || n === 0 ? "" : n > 0 ? "pos" : "neg";
}

export function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
