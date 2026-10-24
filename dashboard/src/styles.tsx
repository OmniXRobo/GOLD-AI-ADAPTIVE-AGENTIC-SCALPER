/** Trade styles: scalping (short holds, tight SL/TP) and swing (hourly bars, wider SL/TP, held up to days). */

export type TradeStyle = "scalp" | "swing";

export const STYLE_INFO: Record<TradeStyle, { label: string; hint: string }> = {
  scalp: { label: "Scalping", hint: "1-15 minute bars, tight SL/TP, held up to 1 hour" },
  swing: { label: "Swing", hint: "15 minute to 4 hour bars, wider SL/TP, held up to 3 days" },
};

/** Style of a signal, trade or engine; records made before styles existed are scalping. */
export function styleOf(x: { style?: unknown; context?: Record<string, unknown> } | null | undefined): TradeStyle {
  const s = x?.style ?? x?.context?.style;
  return s === "swing" ? "swing" : "scalp";
}

export function StyleTag({ style }: { style: TradeStyle }) {
  return (
    <span className={`style-tag style-${style}`} title={STYLE_INFO[style].hint}>
      {STYLE_INFO[style].label}
    </span>
  );
}

/** "All styles" / Scalping / Swing filter chips. `value` null means both. */
export function StyleChips({ value, onChange }: { value: TradeStyle | null; onChange: (v: TradeStyle | null) => void }) {
  const opts: [TradeStyle | null, string][] = [
    [null, "All styles"],
    ["scalp", STYLE_INFO.scalp.label],
    ["swing", STYLE_INFO.swing.label],
  ];
  return (
    <div className="chips chips-scroll">
      {opts.map(([k, l]) => (
        <button key={l} className={`chip ${value === k ? "active" : ""}`} onClick={() => onChange(k)} title={k ? STYLE_INFO[k].hint : undefined}>
          {l}
        </button>
      ))}
    </div>
  );
}

/** "1 hour", "3 days" from seconds. */
export function holdLimit(seconds: unknown): string | null {
  if (typeof seconds !== "number" || seconds <= 0) return null;
  if (seconds >= 86400) {
    const d = Math.round(seconds / 86400);
    return `${d} day${d === 1 ? "" : "s"}`;
  }
  if (seconds >= 3600) {
    const h = Math.round((seconds / 3600) * 10) / 10;
    return `${h} hour${h === 1 ? "" : "s"}`;
  }
  return `${Math.round(seconds / 60)} min`;
}
