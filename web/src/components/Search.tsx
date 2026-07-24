// Ticker search. A button opens a modal overlay with a live-filtered list of
// the tracked universe (tickers/index.json). Works on both desktop and mobile.

import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import ChangeBadge from "./ChangeBadge";
import type { TickerIndexEntry } from "../lib/types";

// Module-level cache: the universe is tiny (~60) and never changes mid-session,
// so load it once and share across every mount of the search overlay.
let cache: TickerIndexEntry[] | null = null;

function useTickers(active: boolean): TickerIndexEntry[] {
  const [items, setItems] = useState<TickerIndexEntry[]>(cache ?? []);
  useEffect(() => {
    if (!active || cache) return;
    let alive = true;
    api
      .tickers()
      .then((d) => {
        cache = d;
        if (alive) setItems(d);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [active]);
  return items;
}

function score(t: TickerIndexEntry, q: string): number {
  const name = t.name.toLowerCase();
  const en = (t.nameEn ?? "").toLowerCase();
  const code = t.code.toLowerCase();
  if (code === q || name === q) return 3;
  if (name.startsWith(q) || en.startsWith(q) || code.startsWith(q)) return 2;
  if (name.includes(q) || en.includes(q) || code.includes(q)) return 1;
  return 0;
}

export default function SearchButton({ compact }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const btn =
    "px-2.5 py-1.5 rounded-lg border text-xs font-medium whitespace-nowrap flex items-center gap-1.5";
  const style = { borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--text)" };
  return (
    <>
      <button
        className={compact ? btn : `${btn} w-full justify-start`}
        style={style}
        onClick={() => setOpen(true)}
        title="종목 검색"
        aria-label="종목 검색"
      >
        <span>🔍</span>
        {!compact && <span style={{ color: "var(--muted)" }}>종목 검색…</span>}
      </button>
      {open && <SearchOverlay onClose={() => setOpen(false)} />}
    </>
  );
}

function SearchOverlay({ onClose }: { onClose: () => void }) {
  const items = useTickers(true);
  const [q, setQ] = useState("");
  const [hi, setHi] = useState(0);
  const nav = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    // lock body scroll while the overlay is open
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [];
    return items
      .map((t) => [t, score(t, s)] as const)
      .filter(([, sc]) => sc > 0)
      .sort((a, b) => b[1] - a[1] || (b[0].marcap ?? 0) - (a[0].marcap ?? 0))
      .slice(0, 8)
      .map(([t]) => t);
  }, [items, q]);

  useEffect(() => setHi(0), [q]);

  const pick = (t: TickerIndexEntry) => {
    onClose();
    nav(`/ticker/${t.market}/${t.code}`);
  };

  const onInputKey = (e: ReactKeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHi((h) => Math.min(h + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHi((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter" && results[hi]) {
      e.preventDefault();
      pick(results[hi]);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]"
      style={{ background: "rgba(0,0,0,0.45)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg card overflow-hidden"
        style={{ background: "var(--surface)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-3.5 py-3 border-b" style={{ borderColor: "var(--border)" }}>
          <span>🔍</span>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onInputKey}
            placeholder="종목명·코드·영문명 검색 (예: 삼성, 005930, apple)"
            className="flex-1 bg-transparent outline-none text-sm"
            style={{ color: "var(--text)" }}
          />
          <button onClick={onClose} className="text-sm px-1.5" style={{ color: "var(--muted)" }} aria-label="닫기">
            ✕
          </button>
        </div>

        {q.trim() === "" ? (
          <div className="px-4 py-6 text-center text-sm" style={{ color: "var(--muted)" }}>
            종목 이름이나 코드를 입력하세요.
          </div>
        ) : results.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm" style={{ color: "var(--muted)" }}>
            "{q}"에 맞는 종목이 없습니다.
          </div>
        ) : (
          <ul className="max-h-[55vh] overflow-y-auto py-1">
            {results.map((t, i) => (
              <li key={`${t.market}:${t.code}`}>
                <button
                  onClick={() => pick(t)}
                  onMouseEnter={() => setHi(i)}
                  className="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left transition"
                  style={i === hi ? { background: "var(--surface-2)" } : undefined}
                >
                  <span className="chip" style={{ padding: "1px 7px", fontSize: 10 }}>
                    {t.market === "KR" ? "🇰🇷" : "🇺🇸"} {t.exchange ?? t.market}
                  </span>
                  <span className="min-w-0">
                    <span className="font-medium">{t.name}</span>
                    <span className="text-xs ml-1.5" style={{ color: "var(--muted)" }}>
                      {t.code}
                      {t.nameEn ? ` · ${t.nameEn}` : ""}
                    </span>
                  </span>
                  <span className="ml-auto shrink-0">
                    <ChangeBadge pct={t.changePct} size="sm" />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
