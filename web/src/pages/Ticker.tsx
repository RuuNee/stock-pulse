import { useRef, useState } from "react";
import { useParams, Navigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { useSettings } from "../lib/settings";
import TickerChart from "../components/TickerChart";
import ChangeBadge from "../components/ChangeBadge";
import NewsCard from "../components/NewsCard";
import Term from "../components/Term";
import { fmtMarcap, fmtPrice, fmtVolume, volLabel } from "../lib/format";
import type { ChartEvent, Market as Mkt, TickerDetail } from "../lib/types";

const RANGES: { label: string; days: number }[] = [
  { label: "1개월", days: 22 },
  { label: "3개월", days: 66 },
  { label: "6개월", days: 132 },
  { label: "1년", days: 252 },
  { label: "2년", days: 500 },
];

const CONF: Record<string, [string, string]> = {
  high: ["🟢", "높음"],
  medium: ["🟡", "보통"],
  low: ["🟠", "낮음"],
};

export default function Ticker() {
  const { market, code } = useParams<{ market: string; code: string }>();
  const m = market?.toUpperCase() as Mkt;
  if ((m !== "KR" && m !== "US") || !code) return <Navigate to="/" replace />;

  const { data, loading, error } = useAsync(() => api.ticker(m, code), [m, code]);
  const s = useSettings();
  const [range, setRange] = useState(132);
  const [showMarkers, setShowMarkers] = useState(true);
  const [showMA, setShowMA] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [watched, setWatched] = useState(() => isWatched(m, code));
  const eventRefs = useRef<Record<string, HTMLDivElement | null>>({});

  if (error) return <div className="card p-8 text-center mt-8">종목 정보를 불러오지 못했습니다.</div>;
  if (loading || !data) return <TickerSkeleton />;

  const d = data as TickerDetail;
  const q = d.quote;

  const jumpToEvent = (ev: ChartEvent) => {
    setActive(ev.id);
    eventRefs.current[ev.id]?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return (
    <div className="flex flex-col gap-4">
      {/* header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-bold">{d.name}</h1>
            <span className="text-sm" style={{ color: "var(--muted)" }}>{d.code}</span>
            <span className="chip" style={{ padding: "2px 8px", fontSize: 11 }}>{d.exchange}</span>
            {d.sector && <span className="chip" style={{ padding: "2px 8px", fontSize: 11 }}>{d.sector}</span>}
          </div>
          <div className="mt-1.5 flex items-baseline gap-3">
            <span className="text-2xl font-bold tabular-nums">{fmtPrice(q.close, d.currency)}</span>
            <ChangeBadge pct={q.changePct} size="lg" showLabel />
          </div>
          <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>
            <Term k="volume">거래량</Term> {fmtVolume(q.volume)} ({volLabel(q.volumeVsAvg20)})
          </div>
        </div>
        <button
          onClick={() => setWatched(toggleWatch(d.market, d.code))}
          className="chip"
          style={watched ? { padding: "8px 12px", borderColor: "var(--up)", color: "var(--up)" } : { padding: "8px 12px" }}
          title="관심 종목"
        >
          {watched ? "♥ 관심" : "♡ 관심"}
        </button>
      </div>

      {/* range + toggles */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1.5">
          {RANGES.map((r) => (
            <button
              key={r.days}
              className={`chip ${range === r.days ? "active" : ""}`}
              onClick={() => setRange(r.days)}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="flex gap-1.5 ml-auto">
          <button className={`chip ${showMarkers ? "active" : ""}`} onClick={() => setShowMarkers((v) => !v)}>
            📍 뉴스 마커
          </button>
          <button className={`chip ${showMA ? "active" : ""}`} onClick={() => setShowMA((v) => !v)}>
            <Term k="ma">이동평균</Term>
          </button>
        </div>
      </div>

      {/* chart */}
      <div className="card p-2 pt-3">
        <TickerChart detail={d} range={range} showMarkers={showMarkers} showMA={showMA} onMarkerClick={jumpToEvent} />
      </div>

      {/* quote stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="시가총액" k="marcap" value={fmtMarcap(q.marcap, d.currency)} />
        <Stat label="52주 최고" value={fmtPrice(q.high52, d.currency)} />
        <Stat label="52주 최저" value={fmtPrice(q.low52, d.currency)} />
        <Stat label="전일 종가" value={fmtPrice(q.prevClose, d.currency)} />
      </div>

      {/* ⭐ event timeline — the point of the whole site */}
      <section>
        <h2 className="text-base font-bold mb-1">📅 급등락일 & 그날의 뉴스</h2>
        <p className="text-xs mb-3" style={{ color: "var(--muted)" }}>
          차트의 ▲▼ 마커를 누르거나 아래에서 바로 확인하세요. 왜 움직였는지 정리했습니다.
        </p>
        {d.events.length === 0 ? (
          <div className="card p-6 text-center text-sm" style={{ color: "var(--muted)" }}>
            최근 큰 움직임이 없었습니다. 조용한 종목이에요.
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {(s.beginner ? d.events.filter((e) => e.severity >= 2 || e.news.length > 0) : d.events).map((e) => (
              <EventCard
                key={e.id}
                e={e}
                currency={d.currency}
                active={active === e.id}
                refCb={(el) => (eventRefs.current[e.id] = el)}
              />
            ))}
          </div>
        )}
      </section>

      {/* recent news */}
      {d.recentNews.length > 0 && (
        <section>
          <h2 className="text-base font-bold mb-2.5">최근 종목 뉴스</h2>
          <div className="flex flex-col gap-2.5">
            {d.recentNews.map((n) => <NewsCard key={n.id} item={n} />)}
          </div>
        </section>
      )}
    </div>
  );
}

function EventCard({
  e,
  currency,
  active,
  refCb,
}: {
  e: ChartEvent;
  currency: string;
  active: boolean;
  refCb: (el: HTMLDivElement | null) => void;
}) {
  const up = e.changePct >= 0;
  const [confDot, confLabel] = CONF[e.confidence] ?? CONF.low;
  return (
    <div
      ref={refCb}
      className="card p-4 transition"
      style={active ? { borderColor: "var(--accent)", boxShadow: "0 0 0 2px var(--accent)33" } : undefined}
    >
      <div className="flex items-center gap-2 text-sm mb-1" style={{ color: "var(--muted)" }}>
        <span>{up ? "▲" : "▼"}</span>
        <span className="font-medium" style={{ color: "var(--text)" }}>{e.date}</span>
        <ChangeBadge pct={e.changePct} size="sm" />
        {e.volumeRatio && e.volumeRatio >= 2.5 && <span>· 거래량 {e.volumeRatio.toFixed(1)}배</span>}
        <span className="ml-auto" style={{ color: "var(--muted)" }}>{fmtPrice(e.close, currency)}</span>
      </div>

      <div className="font-bold">{e.headline}</div>
      <p className="mt-1.5 text-sm leading-relaxed">{e.explain}</p>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--muted)" }}>
        <span>{confDot} 근거 신뢰도: {confLabel}</span>
        {e.source === "llm" && <span>· AI 요약</span>}
        {e.tags.map((t) => (
          <span key={t}>#{t}</span>
        ))}
      </div>

      {e.news.length > 0 && (
        <div className="mt-2.5 pt-2.5 border-t" style={{ borderColor: "var(--border)" }}>
          <div className="text-xs mb-1.5" style={{ color: "var(--muted)" }}>📎 관련 기사 {e.news.length}건</div>
          <div className="flex flex-col gap-1">
            {e.news.map((n, i) => (
              <a key={i} href={n.url} target="_blank" rel="noopener noreferrer" className="text-sm truncate hover:underline">
                · {n.title} <span style={{ color: "var(--muted)" }}>({n.source})</span>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, k }: { label: string; value: string; k?: string }) {
  return (
    <div className="card p-3">
      <div className="text-xs" style={{ color: "var(--muted)" }}>
        {k ? <Term k={k}>{label}</Term> : label}
      </div>
      <div className="font-semibold text-sm mt-0.5 tabular-nums">{value}</div>
    </div>
  );
}

function TickerSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <div className="skeleton" style={{ height: 60 }} />
      <div className="skeleton" style={{ height: 300 }} />
      <div className="grid grid-cols-4 gap-2">
        {Array.from({ length: 4 }).map((_, i) => <div key={i} className="skeleton" style={{ height: 56 }} />)}
      </div>
    </div>
  );
}

// --- localStorage watchlist ---
function watchKey() {
  try {
    return JSON.parse(localStorage.getItem("sp:watch") ?? "[]") as string[];
  } catch {
    return [];
  }
}
function isWatched(market: string, code: string) {
  return watchKey().includes(`${market}:${code}`);
}
function toggleWatch(market: string, code: string): boolean {
  const id = `${market}:${code}`;
  const list = watchKey();
  const has = list.includes(id);
  const next = has ? list.filter((x) => x !== id) : [...list, id];
  localStorage.setItem("sp:watch", JSON.stringify(next));
  return !has;
}
