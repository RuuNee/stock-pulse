// Tiny fetch layer over the static JSON in /data. Caches the last good copy in
// localStorage so a failed refresh still renders something (schema §5, 상태 처리).

import type {
  Brief,
  Manifest,
  Market,
  NewsItem,
  Overview,
  TickerDetail,
  TickerIndexEntry,
} from "./types";

const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");

async function get<T>(path: string, cacheKey?: string): Promise<T> {
  const url = `${BASE}/data/${path}`;
  try {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${res.status} ${url}`);
    const data = (await res.json()) as T;
    if (cacheKey) {
      try {
        localStorage.setItem(`sp:${cacheKey}`, JSON.stringify(data));
      } catch {
        /* quota — ignore */
      }
    }
    return data;
  } catch (err) {
    if (cacheKey) {
      const cached = localStorage.getItem(`sp:${cacheKey}`);
      if (cached) return JSON.parse(cached) as T;
    }
    throw err;
  }
}

export const api = {
  manifest: () => get<Manifest>("manifest.json", "manifest"),
  overview: () => get<Overview>("market/overview.json", "overview"),
  tickers: () =>
    get<{ items: TickerIndexEntry[] }>("tickers/index.json", "tickers").then((d) => d.items),
  ticker: (market: Market, code: string) =>
    get<TickerDetail>(`tickers/${market}/${code}.json`, `t:${market}:${code}`),
  news: () =>
    get<{ items: NewsItem[] }>("news/latest.json", "news").then((d) => d.items),
  brief: (market: Market) => get<Brief>(`brief/latest-${market}.json`, `brief:${market}`),
};
