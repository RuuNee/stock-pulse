import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import ChangeBadge from "../components/ChangeBadge";
import SignalBadge from "../components/SignalBadge";
import { useSettings } from "../lib/settings";
import { fmtDateKr } from "../lib/format";
import { toneOf, verdictColor } from "../lib/signals";
import type { Brief as BriefT, ChartSignals, Market, SignalRef } from "../lib/types";

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
      {data?.late && <LateNotice />}
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

/** 발송 창을 놓쳐 개장 뒤에 만들어진 브리핑. 화면 제목은 "장전 브리핑"이라
 *  붙어 있으므로, 표시가 없으면 개장 전 시점의 이야기로 읽힌다. */
function LateNotice() {
  return (
    <div
      className="card p-3 text-sm leading-relaxed"
      style={{ borderColor: "var(--warn, #b45309)", background: "var(--surface-2)" }}
      role="status"
    >
      ⏰ <b>이 브리핑은 개장 뒤에 만들어졌어요.</b>
      <div className="mt-1" style={{ color: "var(--muted)" }}>
        스케줄러 지연으로 장 시작 전에 발송하지 못했습니다. 이미 장이 열린 상태로 읽어 주세요.
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

      {brief.chartSignals && <ChartSignalSection cs={brief.chartSignals} />}

      {brief.watchlistMoves.length > 0 && (
        <section className="card p-4">
          <h2 className="font-bold mb-2">👀 관심 종목 움직임</h2>
          <div className="flex flex-col gap-2">
            {brief.watchlistMoves.map((w) => (
              <div key={w.code} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate">
                  {w.name}
                  {w.signal && (
                    <span style={{ color: "var(--muted)" }}> · {w.signalEmoji} {w.signal}</span>
                  )}
                  {w.note && <span style={{ color: "var(--muted)" }}> · {w.note}</span>}
                </span>
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

/** 차트 분석 신호 — 뉴스가 아니라 "차트 모양"만 보고 고른 종목들.
 *  뉴스 섹션과 섞이지 않게 별도 카드로 두고, 근거가 지표뿐이라는 점을 밝힌다. */
function ChartSignalSection({ cs }: { cs: ChartSignals }) {
  const { bullish, bearish, counts } = cs;
  if (!bullish.length && !bearish.length) return null;
  const total = counts.bullish + counts.neutral + counts.bearish;

  return (
    <section className="card p-4">
      <div className="flex items-baseline gap-2 mb-1">
        <h2 className="font-bold">📊 차트 분석 신호</h2>
        {cs.asOf && (
          <span className="text-xs" style={{ color: "var(--muted)" }}>{cs.asOf} 종가 기준</span>
        )}
      </div>
      <p className="text-xs mb-3" style={{ color: "var(--muted)" }}>
        추적 {total}종목 · 매수 우위 {counts.bullish} · 관망 {counts.neutral} · 매도 우위 {counts.bearish}
      </p>

      <div className="grid sm:grid-cols-2 gap-4">
        <SignalColumn title="강세 신호" rows={bullish} empty="오늘은 강세 신호가 없습니다." />
        <SignalColumn title="약세 신호" rows={bearish} empty="오늘은 약세 신호가 없습니다." />
      </div>

      <p className="mt-3 pt-2.5 border-t text-xs leading-relaxed" style={{ borderColor: "var(--border)", color: "var(--muted)" }}>
        ⚠️ {cs.note}{" "}
        <Link to="/learn?tab=chart" className="underline" style={{ color: "var(--accent)" }}>
          기법 설명 보기 →
        </Link>
      </p>
    </section>
  );
}

function SignalColumn({ title, rows, empty }: { title: string; rows: SignalRef[]; empty: string }) {
  return (
    <div>
      <h3 className="text-sm font-semibold mb-2">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-xs" style={{ color: "var(--muted)" }}>{empty}</p>
      ) : (
        <div className="flex flex-col gap-2">
          {rows.map((r) => <SignalRow key={`${r.market}:${r.code}`} r={r} />)}
        </div>
      )}
    </div>
  );
}

function SignalRow({ r }: { r: SignalRef }) {
  const s = useSettings();
  const color = verdictColor(toneOf(r.signal), s);
  return (
    <Link
      to={`/ticker/${r.market}/${r.code}`}
      className="rounded-xl border p-2.5 block transition"
      style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}
    >
      <div className="flex items-center gap-2">
        <span className="font-semibold text-sm truncate">{r.name}</span>
        <span className="ml-auto"><ChangeBadge pct={r.changePct} size="sm" /></span>
      </div>
      <div className="mt-1.5 flex items-center gap-2 flex-wrap">
        <SignalBadge a={r} size="sm" />
      </div>
      <div className="mt-1.5 text-xs" style={{ color }}>{r.headline}</div>
    </Link>
  );
}
