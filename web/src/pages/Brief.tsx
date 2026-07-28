import { useState } from "react";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import ChangeBadge from "../components/ChangeBadge";
import { fmtDateKr } from "../lib/format";
import type { Brief as BriefT, Market } from "../lib/types";

export default function Brief() {
  const [market, setMarket] = useState<Market>("KR");
  const { data, loading, error } = useAsync(() => api.brief(market), [market]);
  // 브리핑과 따로 받는다 — manifest 를 못 읽어도 브리핑은 그대로 보여야 한다.
  const { data: manifest } = useAsync(() => api.manifest(), []);

  // 파이프라인이 계산해 둔 "이번에 브리핑이 나가야 할 장" 날짜. 휴장일 판정이
  // 이미 반영돼 있으므로 웹에서 거래일 계산을 다시 할 필요가 없다.
  const expected = manifest?.markets?.[market]?.briefDate;
  // 문자열 비교로 충분하다 (YYYY-MM-DD). manifest 쪽이 더 오래됐을 땐 알리지 않는다 —
  // 헛경보가 침묵보다 나쁘다.
  const staleFor = data && expected && data.date < expected ? expected : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">장전 브리핑</h1>
        <div className="flex gap-1.5">
          <button className={`chip ${market === "KR" ? "active" : ""}`} onClick={() => setMarket("KR")}>국장</button>
          <button className={`chip ${market === "US" ? "active" : ""}`} onClick={() => setMarket("US")}>미장</button>
        </div>
      </div>

      {loading && <div className="skeleton" style={{ height: 320 }} />}
      {error && (
        <div className="card p-8 text-center text-sm" style={{ color: "var(--muted)" }}>
          아직 브리핑이 생성되지 않았습니다. 매일 장 시작 전에 자동으로 만들어집니다.
        </div>
      )}
      {staleFor && <StaleNotice expected={staleFor} />}
      {data && <BriefBody brief={data} />}
    </div>
  );
}

/** 오늘 브리핑이 아직 안 만들어졌을 때. 예전 브리핑을 아무 표시 없이 보여주면
 *  사용자가 날짜를 직접 대조해야 한다 — 2026-07-28 에 실제로 그랬다. */
function StaleNotice({ expected }: { expected: string }) {
  return (
    <div
      className="card p-3 text-sm leading-relaxed"
      style={{ borderColor: "var(--warn, #b45309)", background: "var(--surface-2)" }}
      role="status"
    >
      ⏳ <b>{fmtDateKr(expected)} 브리핑은 아직 준비 중이에요.</b>
      <div className="mt-1" style={{ color: "var(--muted)" }}>
        아래는 그 전 장의 브리핑입니다. 장 시작 전에 자동으로 새로 만들어집니다.
      </div>
    </div>
  );
}

function BriefBody({ brief }: { brief: BriefT }) {
  const dot = { green: "🟢", amber: "🟡", red: "🔴" }[brief.mood.color ?? "amber"];
  return (
    <div className="flex flex-col gap-4">
      <div className="card p-4">
        <div className="text-sm" style={{ color: "var(--muted)" }}>{fmtDateKr(brief.date)}</div>
        {brief.mood.label && (
          <div className="text-lg font-bold mt-1">{dot} 오늘 시장 분위기: {brief.mood.label} ({brief.mood.score}점)</div>
        )}
        {brief.headline && <p className="mt-2 leading-relaxed">{brief.headline}</p>}
      </div>

      <section className="card p-4">
        <h2 className="font-bold mb-2">📌 오늘 꼭 알아야 할 3가지</h2>
        <ol className="flex flex-col gap-2">
          {brief.threeLines.map((line, i) => (
            <li key={i} className="flex gap-2 text-sm leading-relaxed">
              <span className="font-bold" style={{ color: "var(--accent)" }}>{i + 1}</span>
              <span>{line}</span>
            </li>
          ))}
        </ol>
      </section>

      {brief.marketSnapshot.length > 0 && (
        <section className="card p-4">
          <h2 className="font-bold mb-2">📊 간밤 시장</h2>
          <div className="flex flex-col gap-1.5">
            {brief.marketSnapshot.map((s) => (
              <div key={s.name} className="flex items-center justify-between text-sm">
                <span>{s.name}</span>
                <div className="flex items-center gap-3">
                  <span className="tabular-nums">{s.value != null ? s.value.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) : "-"}</span>
                  <ChangeBadge pct={s.changePct} size="sm" />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {brief.topNews.length > 0 && (
        <section className="card p-4">
          <h2 className="font-bold mb-3">📰 주요 뉴스</h2>
          <div className="flex flex-col gap-3">
            {brief.topNews.map((n, i) => (
              <div key={i}>
                <a href={n.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-sm hover:underline">
                  {i + 1}. {n.titleKo || n.title}
                </a>
                {n.why && <div className="mt-1 text-sm rounded-lg px-2.5 py-1.5" style={{ background: "var(--surface-2)" }}>💡 {n.why}</div>}
                <div className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                  {n.tickers.map((t) => t.name).join(" · ")} {n.source && `· ${n.source}`}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {brief.watchlistMoves.length > 0 && (
        <section className="card p-4">
          <h2 className="font-bold mb-2">👀 관심 종목 움직임</h2>
          <div className="flex flex-col gap-1.5">
            {brief.watchlistMoves.map((w) => (
              <div key={w.code} className="flex items-center justify-between text-sm">
                <span className="truncate">{w.name} {w.note && <span style={{ color: "var(--muted)" }}>· {w.note}</span>}</span>
                <ChangeBadge pct={w.changePct} size="sm" />
              </div>
            ))}
          </div>
        </section>
      )}

      <p className="text-xs text-center" style={{ color: "var(--muted)" }}>ℹ️ {brief.disclaimer}</p>
    </div>
  );
}
