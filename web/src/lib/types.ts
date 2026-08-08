// Mirrors md파일/02-데이터스키마.md. Keep in sync with the pipeline.

export type Market = "KR" | "US";

export interface Manifest {
  version: number;
  generatedAt: string;
  generatedAtKst: string;
  counts: { tickers: number; news: number; events: number };
  markets: Record<Market, { lastTradingDay: string | null; briefDate: string }>;
}

export interface MacroIndex {
  key: string;
  name: string;
  market: Market | "GLOBAL";
  group: "index" | "fx" | "rate" | "commodity" | "crypto";
  /** 이 값이 어느 날 마감인지 (YYYY-MM-DD). 장중 스냅샷을 싣지 않으므로 항상 마감일이다. */
  date: string | null;
  value: number | null;
  change: number | null;
  changePct: number | null;
  unit: string;
  spark: number[];
  beginnerNote: string;
}

export interface Sector {
  name: string;
  changePct: number;
  count: number;
  topName: string;
  topPct: number | null;
}

export interface MoverRef {
  code: string;
  name: string;
  market: Market;
  changePct: number | null;
  close: number | null;
  reason: string | null;
}

export interface Mood {
  score: number;
  label: string;
  color: "green" | "amber" | "red";
  reason?: string;
}

export interface Overview {
  generatedAt: string;
  indices: MacroIndex[];
  sectors: Record<Market, Sector[]>;
  movers: Record<Market, { up: MoverRef[]; down: MoverRef[] }>;
  marketMood: Record<Market, Mood>;
}

export interface TickerNews {
  title: string;
  titleKo?: string;
  url: string;
  source?: string;
  publishedAt?: string;
  score?: number;
}

export type EventType = "surge" | "plunge" | "volumeSpike" | "gapUp" | "gapDown";

export interface ChartEvent {
  id: string;
  date: string;
  type: EventType;
  severity: 1 | 2 | 3;
  changePct: number;
  zScore: number | null;
  volumeRatio: number | null;
  gapPct: number | null;
  close: number;
  volume: number;
  headline: string;
  explain: string;
  confidence: "high" | "medium" | "low";
  source: "llm" | "rule";
  tags: string[];
  sentiment: "positive" | "negative" | "neutral";
  news: TickerNews[];
}

// --- 차트 분석 (pipeline/analyze/technical.py) ---

export type Verdict = "bullish" | "bearish" | "neutral";
export type SignalKey = "strongBuy" | "buy" | "neutral" | "sell" | "strongSell";
export type ActionKey =
  | "chase" | "addBuy" | "buy" | "takeProfit"
  | "reduce" | "stopLoss" | "rebound" | "hold";

export interface TechSignal {
  key: string;
  name: string;
  group: string; // 추세 | 모멘텀 | 변동성 | 수급 | 가격대
  verdict: Verdict;
  strength: number; // 0~1
  weight: number; // 1~3
  value: string; // 짧은 수치 표기
  detail: string;
}

/** 목록·브리핑이 쓰는 압축본 (tickers/index.json). */
export interface AnalysisBrief {
  score: number;
  signal: SignalKey;
  label: string;
  action: ActionKey;
  actionEmoji: string;
  actionLabel: string;
  headline: string;
  date: string;
}

export interface TickerAnalysis extends AnalysisBrief {
  actionNote: string;
  summary: string;
  trend: {
    phase: string;
    direction: "up" | "down" | "flat";
    slopePct: number | null;
    label: string;
    aboveMa60: boolean | null;
  };
  counts: { bullish: number; bearish: number; neutral: number };
  signals: TechSignal[];
  levels: {
    support: number | null;
    resistance: number | null;
    supportGapPct: number | null;
    resistanceGapPct: number | null;
    high52: number | null;
    low52: number | null;
    /** 전고점 대비 (음수 = 아래) */
    high52Pct: number | null;
    /** 전저점 대비 (양수 = 위) */
    low52Pct: number | null;
    /** 전저점~전고점 구간의 몇 % 지점인가 (0~100) */
    rangePos: number | null;
  };
  /** 스윙 점 2개를 이은 대각 추세선. 조건이 안 맞으면 null.
   *  이 필드가 생기기 전에 만들어진 종목 파일에는 아예 없다 —
   *  data-sync 가 한 바퀴 돌기 전까지 배포된 데이터가 그렇다. */
  trendlines?: { up: Trendline | null; down: Trendline | null };
  risk: { atrPct: number | null; band: string };
  disclaimer: string;
}

export interface Trendline {
  from: { date: string; price: number };
  to: { date: string; price: number };
  /** 마지막 봉까지 연장했을 때의 값 */
  now: number;
  slopePerDay: number;
  /** 현재가가 추세선 대비 몇 % (양수 = 선 위) */
  gapPct: number | null;
}

export interface Quote {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  prevClose: number | null;
  change: number | null;
  changePct: number | null;
  volume: number;
  volumeVsAvg20: number | null;
  high52: number | null;
  low52: number | null;
  marcap: number | null;
}

export interface NewsItem {
  id: string;
  title: string;
  titleKo?: string;
  summary?: string;
  summaryKo?: string;
  url: string;
  source?: string;
  market: Market | "GLOBAL";
  publishedAt?: string;
  category?: string;
  tags: string[];
  tickers: { code: string; name: string; market: Market; score?: number }[];
  importance?: number;
  sentiment?: "positive" | "negative" | "neutral";
}

export interface TickerIndexEntry {
  code: string;
  name: string;
  nameEn?: string;
  market: Market;
  exchange?: string;
  sector?: string;
  currency: string;
  close: number | null;
  changePct: number | null;
  marcap: number | null;
  spark: number[];
  eventCount: number;
  latestEvent: string | null;
  analysis?: AnalysisBrief | null;
  date?: string;
}

export interface TickerDetail {
  code: string;
  name: string;
  nameEn?: string;
  market: Market;
  exchange?: string;
  sector?: string;
  currency: string;
  updatedAt: string;
  quote: Quote;
  ohlcv: { columns: string[]; rows: (string | number)[][] };
  indicators: Record<string, (number | null)[]>;
  analysis?: TickerAnalysis | null;
  events: ChartEvent[];
  recentNews: NewsItem[];
}

export interface SignalRef extends AnalysisBrief {
  code: string;
  name: string;
  market: Market;
  changePct: number | null;
}

export interface ChartSignals {
  asOf: string | null;
  counts: { bullish: number; neutral: number; bearish: number };
  bullish: SignalRef[];
  bearish: SignalRef[];
  note: string;
}

export interface Brief {
  market: Market;
  date: string;
  generatedAt: string;
  /** 발송 창을 놓쳐 개장 뒤에 만들어진 브리핑. 예전 파일에는 이 필드가 없다. */
  late?: boolean;
  headline: string;
  threeLines: string[];
  mood: Partial<Mood>;
  marketSnapshot: { name: string; value: number | null; changePct: number | null; unit?: string }[];
  topNews: {
    title: string;
    titleKo?: string;
    url: string;
    source?: string;
    why?: string;
    tickers: { code: string; name: string }[];
    importance?: number;
  }[];
  chartSignals?: ChartSignals | null;
  watchlistMoves: {
    code: string;
    name: string;
    changePct: number | null;
    note: string | null;
    signal?: string | null;
    signalEmoji?: string | null;
  }[];
  calendar: { time: string; title: string; importance: string }[];
  disclaimer: string;
  siteUrl?: string;
}
