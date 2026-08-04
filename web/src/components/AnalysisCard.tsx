import { useState } from "react";
import { Link } from "react-router-dom";
import { useSettings } from "../lib/settings";
import { fmtPrice } from "../lib/format";
import { ACTION_TONE, GROUP_ICON, toneOf, verdictColor, VERDICT_MARK, VERDICT_WORD } from "../lib/signals";
import Term from "./Term";
import type { TechSignal, TickerAnalysis, Verdict } from "../lib/types";

const GROUP_ORDER = ["추세", "모멘텀", "변동성", "수급", "가격대"];

/** 종목 상세의 "차트 분석" 카드.
 *
 *  종합 점수 하나만 크게 보여주면 근거 없는 점괘가 된다. 그래서 ①행동 문구
 *  ②그 문구를 만든 지표 목록 ③각 지표의 교과서적 해석을 한 카드 안에 같이 둔다.
 *  11가지 지표를 항상 전부 편다 — 접어 두면 "왜 이 판정인지"를 못 따라간다.
 */
export default function AnalysisCard({ a, currency }: { a: TickerAnalysis; currency: string }) {
  const s = useSettings();
  // 행동 문구와 종합 점수는 서로 다른 것을 말하므로 색도 따로 잡는다.
  const color = verdictColor(ACTION_TONE[a.action] ?? "neutral", s);
  const scoreTone = toneOf(a.signal);
  const scoreColor = verdictColor(scoreTone, s);

  const shown = a.signals;

  return (
    <section className="card p-4 flex flex-col gap-3.5">
      <div className="flex items-center gap-2">
        <h2 className="text-base font-bold">📊 차트 분석</h2>
        <span className="text-xs" style={{ color: "var(--muted)" }}>
          {a.date} 종가 기준 · 지표 11가지
        </span>
      </div>

      {/* 결론 — 행동 문구가 주인공, 점수는 곁들이 */}
      <div
        className="rounded-2xl p-3.5 flex flex-col gap-2"
        style={{ background: "var(--surface-2)", border: `1px solid ${color}44` }}
      >
        <div className="flex items-center gap-2.5">
          <span className="text-3xl leading-none" aria-hidden>{a.actionEmoji}</span>
          <div className="min-w-0">
            <div className="font-bold text-lg leading-tight" style={{ color }}>
              {a.actionLabel}
            </div>
            <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
              종합 판정 {a.label} · {a.trend.label}
            </div>
          </div>
          <div className="ml-auto text-right">
            <div className="text-xl font-bold tabular-nums" style={{ color: scoreColor }}>
              {VERDICT_MARK[scoreTone]} {a.score > 0 ? `+${a.score}` : a.score}
            </div>
            <div className="text-[11px]" style={{ color: "var(--muted)" }}>-100 ~ +100</div>
          </div>
        </div>

        <ScoreBar score={a.score} color={scoreColor} />

        <p className="text-sm leading-relaxed">{a.actionNote}</p>
      </div>

      <p className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>{a.summary}</p>

      {/* 가격대 기준선 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Level label="지지선" value={a.levels.support} gap={a.levels.supportGapPct}
               currency={currency} color={s.upColor} />
        <Level label="저항선" value={a.levels.resistance} gap={a.levels.resistanceGapPct}
               currency={currency} color={s.downColor} />
        <Mini label="추세" value={a.trend.phase}
              sub={a.trend.slopePct == null ? "" : `60일선 ${a.trend.slopePct > 0 ? "+" : ""}${a.trend.slopePct}%`} />
        <Mini label="변동성" value={a.risk.band}
              sub={a.risk.atrPct == null ? "" : `하루 평균 ±${a.risk.atrPct}%`} />
      </div>

      <Range52 levels={a.levels} currency={currency} />
      <Trendlines lines={a.trendlines} currency={currency} />

      {/* 기법별 판정 */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <h3 className="text-sm font-bold">기법별 판정</h3>
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            강세 {a.counts.bullish} · 중립 {a.counts.neutral} · 약세 {a.counts.bearish}
          </span>
        </div>
        <div className="flex flex-col gap-1.5">
          {sortByGroup(shown).map((sig) => (
            <SignalRow key={sig.key} sig={sig} />
          ))}
        </div>
      </div>

      <p className="text-xs leading-relaxed pt-1 border-t" style={{ borderColor: "var(--border)", color: "var(--muted)" }}>
        ⚠️ {a.disclaimer}{" "}
        <Link to="/learn?tab=chart" className="underline" style={{ color: "var(--accent)" }}>
          차트 분석이 처음이라면 →
        </Link>
      </p>
    </section>
  );
}

function sortByGroup(signals: TechSignal[]): TechSignal[] {
  return [...signals].sort(
    (x, y) => GROUP_ORDER.indexOf(x.group) - GROUP_ORDER.indexOf(y.group),
  );
}

/** 한 줄 = 기법 하나. 누르면 "왜 그렇게 읽는지" 설명이 펼쳐진다. */
function SignalRow({ sig }: { sig: TechSignal }) {
  const s = useSettings();
  const [open, setOpen] = useState(false);
  const color = verdictColor(sig.verdict as Verdict, s);
  return (
    <div className="rounded-xl border" style={{ borderColor: "var(--border)" }}>
      <button
        className="w-full flex items-center gap-2 px-2.5 py-2 text-left"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="text-xs w-5 text-center" aria-hidden>{GROUP_ICON[sig.group] ?? "•"}</span>
        <span className="text-sm font-medium truncate">{sig.name}</span>
        <span className="text-xs tabular-nums truncate ml-auto" style={{ color: "var(--muted)" }}>
          {sig.value}
        </span>
        <span className="text-xs font-semibold whitespace-nowrap" style={{ color }}>
          {VERDICT_MARK[sig.verdict]} {VERDICT_WORD[sig.verdict]}
        </span>
        <span className="text-xs" style={{ color: "var(--muted)" }}>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <p className="px-2.5 pb-2.5 -mt-0.5 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
          {sig.detail}
        </p>
      )}
    </div>
  );
}

function ScoreBar({ score, color }: { score: number; color: string }) {
  const pos = ((Math.max(-100, Math.min(100, score)) + 100) / 200) * 100;
  return (
    <div className="relative h-2 rounded-full" style={{ background: "var(--border)" }}>
      <div className="absolute inset-y-0 left-1/2 w-px" style={{ background: "var(--muted)", opacity: 0.5 }} />
      <div
        className="absolute -top-0.5 h-3 w-3 rounded-full border-2"
        style={{ left: `calc(${pos}% - 6px)`, background: color, borderColor: "var(--surface)" }}
      />
    </div>
  );
}

function Level({
  label, value, gap, currency, color,
}: {
  label: string; value: number | null; gap: number | null; currency: string; color: string;
}) {
  return (
    <div className="card p-2.5" style={{ background: "var(--surface-2)" }}>
      <div className="text-xs" style={{ color: "var(--muted)" }}>
        <Term k={label === "지지선" ? "support" : "resistance"}>{label}</Term>
      </div>
      <div className="font-semibold text-sm mt-0.5 tabular-nums">{fmtPrice(value, currency)}</div>
      {gap != null && (
        <div className="text-[11px] tabular-nums" style={{ color }}>
          현재가 대비 {gap > 0 ? "+" : ""}{gap.toFixed(1)}%
        </div>
      )}
    </div>
  );
}

/** 52주 고·저 대비 현재가의 자리.
 *
 *  숫자 두 개(전고점/전저점 대비)와 게이지를 같이 둔다. 두 %만 보면 "그래서
 *  위쪽이야 아래쪽이야"가 한 번에 안 들어오고, 게이지만 두면 "얼마나 빠졌나"를
 *  못 읽는다. 서로 다른 질문에 답하는 값이라 둘 다 필요하다.
 */
function Range52({ levels, currency }: { levels: TickerAnalysis["levels"]; currency: string }) {
  const s = useSettings();
  const { high52, low52, high52Pct, low52Pct, rangePos } = levels;
  if (high52 == null || low52 == null) return null;

  return (
    <div className="card p-3" style={{ background: "var(--surface-2)" }}>
      <h3 className="text-sm font-bold mb-2">52주 고·저 대비</h3>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className="text-xs" style={{ color: "var(--muted)" }}>전고점 대비</div>
          <div className="font-semibold tabular-nums" style={{ color: s.downColor }}>
            {high52Pct == null ? "-" : `${high52Pct > 0 ? "+" : ""}${high52Pct.toFixed(1)}%`}
          </div>
          <div className="text-[11px] tabular-nums" style={{ color: "var(--muted)" }}>
            {fmtPrice(high52, currency)}
          </div>
        </div>
        <div>
          <div className="text-xs" style={{ color: "var(--muted)" }}>전저점 대비</div>
          <div className="font-semibold tabular-nums" style={{ color: s.upColor }}>
            {low52Pct == null ? "-" : `${low52Pct > 0 ? "+" : ""}${low52Pct.toFixed(1)}%`}
          </div>
          <div className="text-[11px] tabular-nums" style={{ color: "var(--muted)" }}>
            {fmtPrice(low52, currency)}
          </div>
        </div>
      </div>

      {rangePos != null && (
        <div className="mt-3">
          <div
            className="relative h-2 rounded-full overflow-hidden"
            style={{ background: `linear-gradient(90deg, ${s.upColor}33, ${s.downColor}33)` }}
          >
            <div
              className="absolute top-1/2 w-1 h-4 rounded-full"
              // 0%·100% 에서 마커 절반이 잘리지 않게 안쪽으로 묶는다.
              style={{
                left: `calc(${Math.min(99, Math.max(1, rangePos))}% - 2px)`,
                transform: "translateY(-50%)",
                background: "var(--text)",
              }}
            />
          </div>
          <div className="flex justify-between text-[11px] mt-1" style={{ color: "var(--muted)" }}>
            <span>저점</span>
            <span className="font-semibold tabular-nums" style={{ color: "var(--text)" }}>
              {rangePos.toFixed(0)}% 지점
            </span>
            <span>고점</span>
          </div>
        </div>
      )}
    </div>
  );
}

/** 대각 추세선 — 차트에 그린 선을 숫자로도 적는다. */
function Trendlines({ lines, currency }: { lines: TickerAnalysis["trendlines"]; currency: string }) {
  const s = useSettings();
  const rows = [
    ["상승추세선", lines.up, s.upColor] as const,
    ["하락추세선", lines.down, s.downColor] as const,
  ].filter(([, tl]) => tl);
  if (rows.length === 0) return null;

  return (
    <div className="card p-3" style={{ background: "var(--surface-2)" }}>
      <h3 className="text-sm font-bold mb-2">
        <Term k="trendline">추세선</Term>
      </h3>
      <div className="flex flex-col gap-2">
        {rows.map(([label, tl, color]) => (
          <div key={label} className="flex items-baseline justify-between gap-2 text-sm">
            <span style={{ color }}>{label}</span>
            <span className="tabular-nums text-right">
              오늘 {fmtPrice(tl!.now, currency)}
              {tl!.gapPct != null && (
                <span className="ml-1.5 text-[11px]" style={{ color: "var(--muted)" }}>
                  현재가 {tl!.gapPct > 0 ? "+" : ""}{tl!.gapPct.toFixed(1)}%
                </span>
              )}
            </span>
          </div>
        ))}
      </div>
      <p className="text-[11px] mt-2" style={{ color: "var(--muted)" }}>
        {rows.map(([label, tl]) => `${label} ${tl!.from.date}~${tl!.to.date}`).join(" · ")} 두 점을
        이어 오늘까지 연장한 값입니다.
      </p>
    </div>
  );
}

function Mini({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-2.5" style={{ background: "var(--surface-2)" }}>
      <div className="text-xs" style={{ color: "var(--muted)" }}>{label}</div>
      <div className="font-semibold text-sm mt-0.5">{value}</div>
      {sub && <div className="text-[11px] tabular-nums" style={{ color: "var(--muted)" }}>{sub}</div>}
    </div>
  );
}
