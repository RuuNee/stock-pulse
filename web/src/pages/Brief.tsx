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

type Tab = Market | "KR-close";

export default function Brief() {
  const [tab, setTab] = useState<Tab>("KR");
  const close = tab === "KR-close";
  const market: Market = close ? "KR" : (tab as Market);
  const { data, loading, error } = useAsync(
    () => (close ? api.closeBrief() : api.brief(market)), [tab]);
  // 브리핑과 따로 받는다 — manifest 를 못 읽어도 브리핑은 그대로 보여야 한다.
  const { data: manifest } = useAsync(() => api.manifest(), []);

  // 파이프라인이 계산해 둔 "이번에 브리핑이 나가야 할 장" 날짜. 휴장일 판정이
  // 이미 반영돼 있으므로 웹에서 거래일 계산을 다시 할 필요가 없다.
  const expected = manifest?.markets?.[market]?.briefDate;
  // 문자열 비교로 충분하다 (YYYY-MM-DD). manifest 쪽이 더 오래됐을 땐 알리지 않는다 —
  // 헛경보가 침묵보다 나쁘다.
  // 마감 브리핑은 큰 변동일에만 있으니 "준비 중" 판정을 하지 않는다.
  const staleFor = !close && data && expected && data.date < expected ? expected : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{close ? "장 마감 브리핑" : "장전 브리핑"}</h1>
        <div className="flex gap-1.5">
          <button className={`chip ${tab === "KR" ? "active" : ""}`} onClick={() => setTab("KR")}>국장</button>
          <button className={`chip ${tab === "US" ? "active" : ""}`} onClick={() => setTab("US")}>미장</button>
          <button className={`chip ${close ? "active" : ""}`} onClick={() => setTab("KR-close")}>국장 마감</button>
        </div>
      </div>

      {loading && <div className="skeleton" style={{ height: 320 }} />}
      {error && (
        <div className="card p-8 text-center text-sm" style={{ color: "var(--muted)" }}>
          {close
            ? "아직 장 마감 브리핑이 없습니다. 코스피가 ±2% 넘게 움직인 날, 장 마감(15:30) 뒤에 만들어집니다."
            : "아직 브리핑이 생성되지 않았습니다. 매일 장 시작 전에 자동으로 만들어집니다."}
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
  // 예전 파일(kind 없음)의 점수는 전날 기준 분위기였다 — 전망이라고 부르지 않는다.
  const moodTitle = brief.mood.kind === "outlook" ? "오늘 장 전망" : "오늘 시장 분위기";
  const analysis = brief.analysis ?? [];
  return (
    <div className="flex flex-col gap-4">
      <div className="card p-4">
        <div className="text-sm" style={{ color: "var(--muted)" }}>
          {fmtDateKr(brief.date)}
          {brief.kind === "close" && " · 15:30 마감 · 코스피가 ±2% 넘게 움직인 날에만 만들어집니다"}
        </div>
        {brief.mood.label && (
          <div className="text-lg font-bold mt-1">{dot} {moodTitle}: {brief.mood.label} ({brief.mood.score}점)</div>
        )}
        {brief.mood.reason && (
          <div className="mt-0.5 text-sm" style={{ color: "var(--muted)" }}>{brief.mood.reason}</div>
        )}
        {brief.headline && <p className="mt-2 font-semibold leading-relaxed">{brief.headline}</p>}
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

      {analysis.length > 0 ? (
        <AnalysisSection sections={analysis} />
      ) : (
        (brief.wrapHeadlines?.length ?? 0) > 0 && <WrapSection items={brief.wrapHeadlines!} />
      )}

      {brief.marketSnapshot.length > 0 && (
        <section className="card p-4">
          <h2 className="font-bold mb-2">📊 지표</h2>
          <div className="flex flex-col gap-1.5">
            {brief.marketSnapshot.map((s) => (
              <div key={s.name} className="flex items-center justify-between text-sm">
                <span>{s.name}</span>
                <div className="flex items-center gap-3">
                  <span className="tabular-nums">
                    {s.value != null
                      ? s.value.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) + (s.unit === "%" ? "%" : "")
                      : "-"}
                  </span>
                  {/* 금리는 % 변화율이 아니라 bp 로 — "-0.52%" 는 0.52%p 하락으로 오해된다 */}
                  {s.unit === "%" && s.change != null ? (
                    <span className="text-xs tabular-nums" style={{ color: "var(--muted)" }}>
                      {s.change >= 0 ? "+" : ""}{Math.round(s.change * 100)}bp
                    </span>
                  ) : (
                    <ChangeBadge pct={s.changePct} size="sm" />
                  )}
                </div>
              </div>
            ))}
          </div>
          {(brief.leaders?.length ?? 0) > 0 && (
            <p className="mt-2.5 pt-2 border-t text-xs leading-relaxed" style={{ borderColor: "var(--border)", color: "var(--muted)" }}>
              시총 상위 · {brief.leaders!.map((r) => `${r.name} ${r.changePct >= 0 ? "+" : ""}${r.changePct.toFixed(1)}%`).join(" · ")}
            </p>
          )}
          {brief.flows?.KOSPI && (
            <p className="mt-2.5 pt-2 border-t text-xs leading-relaxed" style={{ borderColor: "var(--border)", color: "var(--muted)" }}>
              수급(코스피 {brief.flows.KOSPI.date.slice(5)}) · 외국인 {eok(brief.flows.KOSPI.foreign)} · 기관{" "}
              {eok(brief.flows.KOSPI.institution)} · 개인 {eok(brief.flows.KOSPI.individual)}
            </p>
          )}
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

      {(brief.calendar?.length ?? 0) > 0 && <CalendarSection items={brief.calendar!} market={brief.market} />}

      {(brief.overnightUs?.length ?? 0) > 0 && <OvernightSection items={brief.overnightUs!} />}

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

/** 🧭 시장 해설 — 왜 움직였고 무엇이 이어지고 앞으로 무엇을 볼지. 텔레그램과 같은 순서. */
function AnalysisSection({ sections }: { sections: { title: string; body: string }[] }) {
  return (
    <section className="card p-4">
      <h2 className="font-bold mb-2">🧭 시장 해설</h2>
      <div className="flex flex-col gap-3">
        {sections.map((sec, i) => (
          <div key={i}>
            <h3 className="text-sm font-semibold" style={{ color: "var(--accent)" }}>▸ {sec.title}</h3>
            <p className="mt-1 text-sm leading-relaxed">{sec.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/** 해설을 못 만든 날(LLM 실패)의 대체 — 원인을 직접 다룬 시황 기사 제목. */
function WrapSection({ items }: { items: NonNullable<BriefT["wrapHeadlines"]> }) {
  return (
    <section className="card p-4">
      <h2 className="font-bold mb-2">🧭 시황 기사</h2>
      <div className="flex flex-col gap-2">
        {items.slice(0, 3).map((w, i) => (
          <a key={i} href={w.url} target="_blank" rel="noopener noreferrer" className="text-sm hover:underline">
            • {w.title}
            {w.source && <span style={{ color: "var(--muted)" }}> · {w.source}</span>}
          </a>
        ))}
      </div>
    </section>
  );
}

/** 억 원 → "-3조 7,637억" (파이프라인 flows.eok_label 과 같은 꼴) */
function eok(v: number): string {
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  const a = Math.abs(v);
  const jo = Math.floor(a / 10000);
  const rest = a % 10000;
  if (jo) return `${sign}${jo}조${rest ? ` ${rest.toLocaleString("ko-KR")}억` : ""}`;
  return `${sign}${rest.toLocaleString("ko-KR")}억`;
}

/** 📅 오늘 예정 — 브리핑에서 유일하게 앞을 보는 블록. 국장 브리핑에는 그날 밤
 *  미국장 일정 중 한국 증시와 이어진 종목만 실린다. 텔레그램 렌더러와 같은 이름. */
function CalendarSection({ items, market }: { items: NonNullable<BriefT["calendar"]>; market: Market }) {
  return (
    <section className="card p-4">
      <h2 className="font-bold mb-2">{market === "KR" ? "📅 오늘 밤 미국 실적" : "📅 오늘 예정"}</h2>
      <div className="flex flex-col gap-2">
        {items.map((c, i) => (
          <div key={c.code ?? i} className="flex items-start justify-between gap-2 text-sm">
            <span className="min-w-0">
              {c.importance === "high" && <span title="시가총액 상위">⭐ </span>}
              <span className="font-semibold">{c.title}</span>
              {c.epsForecast && (
                <span style={{ color: "var(--muted)" }}> · EPS 전망 {c.epsForecast}</span>
              )}
            </span>
            <span className="shrink-0 text-xs whitespace-nowrap" style={{ color: "var(--muted)" }}>
              🕐 {c.time || "시간 미정"}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** 🌏 밤사이 미국 — 국장 브리핑 전용. 미장은 05:00 KST 에 닫혀서 독자가 아직 못 본
 *  기사들이다. 지수만 보여주는 "간밤 시장"이 못 채우는 자리를 종목 단위로 메운다. */
function OvernightSection({ items }: { items: NonNullable<BriefT["overnightUs"]> }) {
  return (
    <section className="card p-4">
      <h2 className="font-bold mb-3">🌏 밤사이 미국 — 종목</h2>
      <div className="flex flex-col gap-3">
        {items.map((n, i) => (
          <div key={i}>
            <a href={n.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-sm hover:underline">
              {n.titleKo || n.title}
            </a>
            <div className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
              {n.tickers.map((t) => t.name).join(" · ")} {n.source && `· ${n.source}`}
            </div>
          </div>
        ))}
      </div>
    </section>
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
