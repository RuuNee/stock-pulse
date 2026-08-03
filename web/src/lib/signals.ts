// 차트 분석 결과를 화면에 옮길 때 쓰는 공통 매핑.
// 판정 자체는 pipeline/analyze/technical.py 가 하고, 여기서는 색·기호만 정한다.

import type { ActionKey, SignalKey, Verdict } from "./types";

export function toneOf(signal: SignalKey | undefined): Verdict {
  if (signal === "strongBuy" || signal === "buy") return "bullish";
  if (signal === "strongSell" || signal === "sell") return "bearish";
  return "neutral";
}

/** 행동 신호의 색. 종합 점수 구간과 **따로** 둔다 — 점수가 -10(중립)이어도
 *  데드크로스가 나면 행동은 "비중 축소"라, 점수 색을 쓰면 회색 칩에 빨간 문구가
 *  붙어 읽기 어색해진다. 차익실현·반등확인은 어느 쪽도 아닌 '주의'라 중립. */
export const ACTION_TONE: Record<ActionKey, Verdict> = {
  chase: "bullish",
  addBuy: "bullish",
  buy: "bullish",
  rebound: "neutral",
  takeProfit: "neutral",
  hold: "neutral",
  reduce: "bearish",
  stopLoss: "bearish",
};

// 색만으로 구분하지 않는다 (UIUX §4 — 색맹 대비).
export const VERDICT_MARK: Record<Verdict, string> = {
  bullish: "▲",
  bearish: "▼",
  neutral: "―",
};

export const VERDICT_WORD: Record<Verdict, string> = {
  bullish: "강세",
  bearish: "약세",
  neutral: "중립",
};

/** 지표 색 약속.
 *
 *  종목 차트(`TickerChart`)와 도움말 예시(`PatternChart`)가 **같은 상수**를 봐야
 *  "주황이 5일선"이라는 설명이 화면과 어긋나지 않는다. 예전에는 양쪽이 각자
 *  하드코딩하고 있었고, 초보모드의 20일선만 주황으로 그려지면서 도움말의
 *  "보라 20일선"과 실제로 맞지 않았다.
 */
export interface IndicatorStyle {
  color: string;
  label: string;
  dash?: boolean;
}

export const INDICATOR = {
  ma5: { color: "#f59e0b", label: "5일선" },
  ma20: { color: "#a855f7", label: "20일선" },
  ma60: { color: "#06b6d4", label: "60일선" },
  ma120: { color: "#64748b", label: "120일선" },
  bb: { color: "#22c55e", label: "볼린저밴드 (20일 ±2σ)", dash: true },
  macd: { color: "#6366f1", label: "MACD" },
  macdSignal: { color: "#f59e0b", label: "시그널선", dash: true },
  rsi: { color: "#a855f7", label: "RSI (14일)" },
  stochK: { color: "#a855f7", label: "%K" },
  stochD: { color: "#f59e0b", label: "%D", dash: true },
} satisfies Record<string, IndicatorStyle>;

/** 지표 묶음별 이모지 — 목록에서 눈으로 그룹을 가르는 용도. */
export const GROUP_ICON: Record<string, string> = {
  추세: "📐",
  모멘텀: "⚡",
  변동성: "🎢",
  수급: "💧",
  가격대: "🎯",
};

export function verdictColor(
  verdict: Verdict,
  s: { upColor: string; downColor: string },
): string {
  if (verdict === "bullish") return s.upColor;
  if (verdict === "bearish") return s.downColor;
  return "var(--muted)";
}
