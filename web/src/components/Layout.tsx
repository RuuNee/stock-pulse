import { type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useSettings } from "../lib/settings";
import SearchButton from "./Search";
import StaleBanner from "./StaleBanner";

const NAV = [
  { to: "/", label: "홈", icon: "🏠", end: true },
  { to: "/market/KR", label: "국장", icon: "🇰🇷" },
  { to: "/market/US", label: "미장", icon: "🇺🇸" },
  { to: "/news", label: "뉴스", icon: "📰" },
  { to: "/brief", label: "브리핑", icon: "📌" },
];

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      {/* desktop sidebar */}
      <aside
        className="hidden md:flex md:flex-col md:w-56 md:shrink-0 md:sticky md:top-0 md:h-screen border-r p-4 gap-1"
        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      >
        <Brand />
        <div className="mt-4">
          <SearchButton />
        </div>
        <nav className="mt-3 flex flex-col gap-1">
          {NAV.map((n) => (
            <SideLink key={n.to} {...n} />
          ))}
          <SideLink to="/learn" label="용어사전" icon="📖" />
        </nav>
        <div className="mt-auto flex flex-col gap-2 text-sm">
          <Toggles />
        </div>
      </aside>

      {/* main column */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header
          className="md:hidden sticky top-0 z-20 flex items-center justify-between px-4 h-14 border-b"
          style={{ borderColor: "var(--border)", background: "var(--surface)" }}
        >
          <Brand />
          <div className="flex items-center gap-2">
            <SearchButton compact />
            <Toggles compact />
          </div>
        </header>

        {/* 페이지가 아니라 데이터 전체가 낡은 상태라 레이아웃에 둔다 — 어느 화면에서도 보인다. */}
        <main className="flex-1 w-full max-w-5xl mx-auto px-4 py-4 pb-24 md:pb-8">
          <StaleBanner />
          {children}
        </main>
      </div>

      {/* mobile bottom tab bar */}
      <nav
        className="md:hidden fixed bottom-0 inset-x-0 z-20 grid grid-cols-5 border-t"
        style={{ borderColor: "var(--border)", background: "var(--surface)", paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {NAV.map((n) => (
          <TabLink key={n.to} {...n} />
        ))}
      </nav>
    </div>
  );
}

function Brand() {
  return (
    <NavLink to="/" className="flex items-center gap-2">
      <span className="text-xl">📈</span>
      <span className="font-bold text-lg tracking-tight">Stock&nbsp;Pulse</span>
    </NavLink>
  );
}

function SideLink({ to, label, icon, end }: { to: string; label: string; icon: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className="flex items-center gap-3 px-3 py-2 rounded-xl text-sm font-medium transition"
      style={({ isActive }) =>
        isActive
          ? { background: "var(--accent)", color: "#fff" }
          : { color: "var(--muted)" }
      }
    >
      <span>{icon}</span>
      <span>{label}</span>
    </NavLink>
  );
}

function TabLink({ to, label, icon, end }: { to: string; label: string; icon: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className="flex flex-col items-center justify-center gap-0.5 py-2 text-[11px]"
      style={({ isActive }) => ({ color: isActive ? "var(--accent)" : "var(--muted)" })}
    >
      <span className="text-lg leading-none">{icon}</span>
      {label}
    </NavLink>
  );
}

function Toggles({ compact }: { compact?: boolean }) {
  const s = useSettings();
  const btn =
    "px-2.5 py-1.5 rounded-lg border text-xs font-medium whitespace-nowrap";
  const style = { borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--text)" };
  return (
    <>
      <button className={btn} style={s.beginner ? { ...style, borderColor: "var(--accent)", color: "var(--accent)" } : style} onClick={s.toggleBeginner}>
        {s.beginner ? "🟢 초보모드" : "초보모드 끔"}
      </button>
      {!compact && (
        <button className={btn} style={style} onClick={s.toggleColorMode}>
          {s.colorMode === "kr" ? "🔴 상승 / 🔵 하락" : "🟢 상승 / 🔴 하락"}
        </button>
      )}
      <button className={btn} style={style} onClick={s.toggleTheme}>
        {s.theme === "dark" ? "🌙" : "☀️"}
      </button>
    </>
  );
}
