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
 *  초보 모드에서는 방향이 잡힌 지표만 추려 보여주고, 고급 모드에서 11가지 전부.
 */
export default function AnalysisCard({ a, currency }: { a: TickerAnalysis; currency: string }) {
  const s = useSettings();
  const [openAll, setOpenAll] = useState(false);
  // 행동 문구와 종합 점수는 서로 다른 것을 말하므로 색도 따로 잡는다.
  const color = verdictColor(ACTION_TONE[a.action] ?? "neutral", s);
  const scoreTone = toneOf(a.signal);
  const scoreColor = verdictColor(scoreTone, s);

  const meaningful = a.signals.filter((x) => x.verdict !== "neutral");
  const shown = s.beginner && !openAll ? meaningful.slice(0, 4) : a.signals;

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

      {/* 기법별 판정 */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <h3 className="text-sm font-bold">기법별 판정</h3>
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            강세 {a.counts.bullish} · 중립 {a.counts.neutral} · 약세 {a.counts.bearish}
          </span>
          {s.beginner && meaningful.length > 4 && (
            <button
              className="ml-auto text-xs"
              style={{ color: "var(--accent)" }}
              onClick={() => setOpenAll((v) => !v)}
            >
              {openAll ? "간단히 보기" : `전체 ${a.signals.length}개 보기`}
            </button>
          )}
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

function Mini({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-2.5" style={{ background: "var(--surface-2)" }}>
      <div className="text-xs" style={{ color: "var(--muted)" }}>{label}</div>
      <div className="font-semibold text-sm mt-0.5">{value}</div>
      {sub && <div className="text-[11px] tabular-nums" style={{ color: "var(--muted)" }}>{sub}</div>}
    </div>
  );
}
