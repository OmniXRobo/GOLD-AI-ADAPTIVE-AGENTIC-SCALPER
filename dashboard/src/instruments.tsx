import { api, type Instrument } from "./api";
import { useApi } from "./lib";

/** Display conventions per instrument. Mirrors gold_ai/instruments.py; the server's /api/instruments wins when present. */
export const INSTRUMENT_INFO: Record<string, { label: string; pip: number; digits: number }> = {
  XAUUSD: { label: "Gold", pip: 0.1, digits: 2 },
  BTCUSD: { label: "Bitcoin", pip: 1, digits: 2 },
  EURUSD: { label: "EUR/USD", pip: 0.0001, digits: 5 },
  GBPUSD: { label: "GBP/USD", pip: 0.0001, digits: 5 },
  USDJPY: { label: "USD/JPY", pip: 0.01, digits: 3 },
  USDCHF: { label: "USD/CHF", pip: 0.0001, digits: 5 },
  AUDUSD: { label: "AUD/USD", pip: 0.0001, digits: 5 },
  USDCAD: { label: "USD/CAD", pip: 0.0001, digits: 5 },
  NZDUSD: { label: "NZD/USD", pip: 0.0001, digits: 5 },
};

const ALIASES: Record<string, string> = { GOLD: "XAUUSD", BITCOIN: "BTCUSD" };

/** Canonical instrument for a broker symbol (XAUUSD.sd -> XAUUSD, EURUSDm -> EURUSD), or null. */
export function canonical(symbol: unknown): string | null {
  const s = String(symbol ?? "").toUpperCase();
  for (const name of [...Object.keys(INSTRUMENT_INFO), ...Object.keys(ALIASES)]) {
    if (s.startsWith(name) && /^[._\-+#]?[A-Z0-9]{0,6}$/.test(s.slice(name.length))) return ALIASES[name] ?? name;
  }
  return null;
}

export function pipSize(symbol: unknown): number | null {
  const c = canonical(symbol);
  return c ? INSTRUMENT_INFO[c].pip : null;
}

export function priceDigits(symbol: unknown, fallback = 2): number {
  const c = canonical(symbol);
  return c ? INSTRUMENT_INFO[c].digits : fallback;
}

export function instrumentLabel(symbol: unknown): string {
  const c = canonical(symbol);
  return c ? INSTRUMENT_INFO[c].label : String(symbol ?? "");
}

/** Human description of one pip, e.g. "1 pip = 0.0001 on EUR/USD". */
export function pipText(symbol: string): string {
  const c = canonical(symbol);
  if (!c) return "";
  const { pip, label } = INSTRUMENT_INFO[c];
  return c === "XAUUSD" || c === "BTCUSD" ? `1 pip = $${pip < 1 ? pip.toFixed(2) : pip} of ${label.toLowerCase()} price` : `1 pip = ${pip} on ${label}`;
}

/** Instruments the live service is running (real engines only; empty when none). */
export function useInstruments(refreshMs = 15000) {
  return useApi<Instrument[]>(api.instruments, [], refreshMs);
}

/** Canonical instruments to offer as filters: the ones running, plus any found in the data shown. */
export function instrumentChoices(running: Instrument[] | null, seen: unknown[] = []): string[] {
  const out: string[] = [];
  for (const i of running ?? []) if (!out.includes(i.instrument)) out.push(i.instrument);
  for (const s of seen) {
    const c = canonical(s);
    if (c && !out.includes(c)) out.push(c);
  }
  return out;
}

/** Filter chips: "All" plus one chip per instrument. `value` null means all. */
export function SymbolChips({ choices, value, onChange, allLabel = "All" }: { choices: string[]; value: string | null; onChange: (v: string | null) => void; allLabel?: string | null }) {
  if (choices.length < (allLabel === null ? 1 : 2)) return null;
  return (
    <div className="chips chips-scroll">
      {allLabel !== null && (
        <button className={`chip ${value === null ? "active" : ""}`} onClick={() => onChange(null)}>
          {allLabel}
        </button>
      )}
      {choices.map((c) => (
        <button key={c} className={`chip ${value === c ? "active" : ""}`} onClick={() => onChange(c)}>
          {INSTRUMENT_INFO[c]?.label ?? c}
        </button>
      ))}
    </div>
  );
}
