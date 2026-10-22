import { useCallback, useEffect, useState } from "react";

export type ThemePref = "dark" | "light" | "auto";
const KEY = "gold_ai_theme_v2"; // v2: cream light theme became the default

function read(): ThemePref {
  try {
    const v = window.localStorage.getItem(KEY);
    if (v === "dark" || v === "light" || v === "auto") return v;
  } catch {
    /* storage blocked */
  }
  return "light";
}

export function applyTheme(p: ThemePref = read()): void {
  const root = document.documentElement;
  if (p === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", p);
  const dark = p === "dark" || (p === "auto" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#0b0d12" : "#f3ede2");
}

const ORDER: ThemePref[] = ["light", "dark", "auto"];

export function useTheme(): [ThemePref, () => void] {
  const [pref, setPref] = useState<ThemePref>(read);
  useEffect(() => {
    applyTheme(pref);
    try {
      window.localStorage.setItem(KEY, pref);
    } catch {
      /* storage blocked */
    }
  }, [pref]);
  const cycle = useCallback(() => setPref((p) => ORDER[(ORDER.indexOf(p) + 1) % ORDER.length]), []);
  return [pref, cycle];
}
