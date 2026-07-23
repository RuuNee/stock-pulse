// Global UI preferences: beginner mode, color convention, theme.
// Persisted to localStorage; consumed via useSettings().

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type Theme = "light" | "dark";
type ColorMode = "kr" | "us"; // kr: 상승=빨강, us: 상승=초록

interface Settings {
  beginner: boolean;
  theme: Theme;
  colorMode: ColorMode;
  toggleBeginner: () => void;
  toggleTheme: () => void;
  toggleColorMode: () => void;
  // resolve up/down to a semantic class suffix
  upColor: string;
  downColor: string;
  colorFor: (pct: number | null | undefined) => string;
}

const Ctx = createContext<Settings | null>(null);

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v == null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [beginner, setBeginner] = useState(() => load("sp:beginner", true));
  const [theme, setTheme] = useState<Theme>(() => load("sp:theme", "dark"));
  const [colorMode, setColorMode] = useState<ColorMode>(() => load("sp:color", "kr"));

  useEffect(() => localStorage.setItem("sp:beginner", JSON.stringify(beginner)), [beginner]);
  useEffect(() => localStorage.setItem("sp:theme", JSON.stringify(theme)), [theme]);
  useEffect(() => localStorage.setItem("sp:color", JSON.stringify(colorMode)), [colorMode]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const value = useMemo<Settings>(() => {
    const up = colorMode === "kr" ? "var(--up)" : "var(--us-up)";
    const down = colorMode === "kr" ? "var(--down)" : "var(--us-down)";
    return {
      beginner,
      theme,
      colorMode,
      toggleBeginner: () => setBeginner((b) => !b),
      toggleTheme: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
      toggleColorMode: () => setColorMode((c) => (c === "kr" ? "us" : "kr")),
      upColor: up,
      downColor: down,
      colorFor: (pct) => (pct == null ? "var(--muted)" : pct >= 0 ? up : down),
    };
  }, [beginner, theme, colorMode]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSettings(): Settings {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSettings outside provider");
  return ctx;
}
