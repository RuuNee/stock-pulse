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
  summary?: string;
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
  events: ChartEvent[];
  recentNews: NewsItem[];
}

export interface Brief {
  market: Market;
  date: string;
  generatedAt: string;
  headline: string;
  threeLines: string[];
  mood: Partial<Mood>;
  marketSnapshot: { name: string; value: number | null; changePct: number | null; unit?: string }[];
  topNews: {
    title: string;
    url: string;
    source?: string;
    why?: string;
    tickers: { code: string; name: string }[];
    importance?: number;
  }[];
  watchlistMoves: { code: string; name: string; changePct: number | null; note: string | null }[];
  calendar: { time: string; title: string; importance: string }[];
  disclaimer: string;
  siteUrl?: string;
}
