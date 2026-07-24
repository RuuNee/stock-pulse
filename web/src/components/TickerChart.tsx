import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { ChartEvent, TickerDetail } from "../lib/types";
import { useSettings } from "../lib/settings";
import { fmtPrice, fmtVolume } from "../lib/format";
import ChangeBadge from "./ChangeBadge";

interface Props {
  detail: TickerDetail;
  range: number; // trading days to show
  showMarkers: boolean;
  showMA: boolean;
  onEventNews: (event: ChartEvent) => void;
}

// A single clicked bar's detail, shown in the overlay panel.
interface BarSel {
  date: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  pct: number | null;
  event: ChartEvent | null;
}

function toTime(dateStr: string): UTCTimestamp {
  return (Date.parse(dateStr + "T00:00:00Z") / 1000) as UTCTimestamp;
}

export default function TickerChart({ detail, range, showMarkers, showMA, onEventNews }: Props) {
  const holder = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const s = useSettings();
  const [sel, setSel] = useState<BarSel | null>(null);

  // Clear the detail panel whenever the chart is rebuilt (range/mode change).
  useEffect(() => setSel(null), [detail.code, range, s.beginner]);

  useEffect(() => {
    const el = holder.current;
    if (!el) return;

    const dark = s.theme === "dark";
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: dark ? "#93a3b8" : "#5b6b82",
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: dark ? "#1b2740" : "#eef2f9" },
        horzLines: { color: dark ? "#1b2740" : "#eef2f9" },
      },
      rightPriceScale: { borderColor: dark ? "#263449" : "#dbe3ef" },
      timeScale: { borderColor: dark ? "#263449" : "#dbe3ef", rightOffset: 4 },
      crosshair: { mode: 1 },
      localization: {
        locale: "ko-KR",
        priceFormatter: (p: number) =>
          detail.currency === "USD" ? `$${p.toFixed(2)}` : Math.round(p).toLocaleString("ko-KR"),
      },
    });
    chartRef.current = chart;

    const upC = s.colorMode === "kr" ? "#e11d48" : "#16a34a";
    const downC = s.colorMode === "kr" ? "#2563eb" : "#dc2626";

    const rows = detail.ohlcv.rows;
    const startIdx = Math.max(0, rows.length - range);
    const slice = rows.slice(startIdx);

    // --- volume (background histogram) ---
    const volSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: "vol",
      priceFormat: { type: "volume" },
      color: dark ? "#26344966" : "#dbe3ef",
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volSeries.setData(
      slice.map((r) => ({
        time: toTime(r[0] as string),
        value: r[5] as number,
        color: (r[4] as number) >= (r[1] as number) ? `${upC}55` : `${downC}55`,
      })),
    );

    // --- price: candles (advanced) or close line (beginner) ---
    let priceSeries: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">;
    if (s.beginner) {
      const line = chart.addSeries(LineSeries, { color: "#6366f1", lineWidth: 2 });
      line.setData(slice.map((r) => ({ time: toTime(r[0] as string), value: r[4] as number })));
      priceSeries = line;
    } else {
      const candle = chart.addSeries(CandlestickSeries, {
        upColor: upC,
        downColor: downC,
        borderUpColor: upC,
        borderDownColor: downC,
        wickUpColor: upC,
        wickDownColor: downC,
      });
      candle.setData(
        slice.map((r) => ({
          time: toTime(r[0] as string),
          open: r[1] as number,
          high: r[2] as number,
          low: r[3] as number,
          close: r[4] as number,
        })),
      );
      priceSeries = candle;
    }

    // --- moving averages ---
    if (showMA) {
      const maDefs: [string, string][] = s.beginner
        ? [["ma20", "#f59e0b"]]
        : [["ma5", "#f59e0b"], ["ma20", "#a855f7"], ["ma60", "#06b6d4"]];
      for (const [key, color] of maDefs) {
        const series = detail.indicators[key];
        if (!series) continue;
        const maLine = chart.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
        maLine.setData(
          slice
            .map((r, i) => ({ time: toTime(r[0] as string), value: series[startIdx + i] }))
            .filter((p): p is { time: UTCTimestamp; value: number } => p.value != null),
        );
      }
    }

    // --- event markers (visual hint only; click detail handled below) ---
    if (showMarkers) {
      const firstDate = slice[0]?.[0] as string | undefined;
      const events = detail.events.filter(
        (e) =>
          (!firstDate || e.date >= firstDate) &&
          (!s.beginner || e.severity >= 2 || e.news.length > 0),
      );
      const markers: SeriesMarker<Time>[] = events.map((e) => {
        const positive = e.changePct >= 0;
        return {
          time: toTime(e.date),
          position: positive ? "aboveBar" : "belowBar",
          color: e.type === "volumeSpike" ? "#f59e0b" : positive ? upC : downC,
          shape: e.type === "volumeSpike" ? "circle" : positive ? "arrowUp" : "arrowDown",
          size: e.severity,
          text: e.headline.length > 12 ? e.headline.slice(0, 12) + "…" : e.headline,
        };
      });
      createSeriesMarkers(priceSeries, markers);
    }

    // --- click a bar → show its OHLC detail (with a news button if that day
    //     has a matched event). Replaces the old "click jumps to news". ---
    chart.subscribeClick((param) => {
      if (param.time == null) {
        setSel(null);
        return;
      }
      const t = param.time as number;
      const i = slice.findIndex((r) => toTime(r[0] as string) === t);
      if (i < 0) {
        setSel(null);
        return;
      }
      const r = slice[i];
      const globalIdx = startIdx + i;
      const prevClose = globalIdx > 0 ? (rows[globalIdx - 1][4] as number) : null;
      const c = r[4] as number;
      const date = r[0] as string;
      setSel({
        date,
        o: r[1] as number,
        h: r[2] as number,
        l: r[3] as number,
        c,
        v: r[5] as number,
        pct: prevClose ? ((c - prevClose) / prevClose) * 100 : null,
        event: detail.events.find((e) => e.date === date) ?? null,
      });
    });

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.code, range, showMarkers, showMA, s.beginner, s.theme, s.colorMode]);

  return (
    <div className="relative w-full">
      <div ref={holder} className="w-full" style={{ height: "min(52vh, 460px)", minHeight: 260 }} />
      {sel && (
        <BarDetail
          sel={sel}
          currency={detail.currency}
          onNews={() => {
            if (sel.event) onEventNews(sel.event);
            setSel(null);
          }}
          onClose={() => setSel(null)}
        />
      )}
    </div>
  );
}

function BarDetail({
  sel,
  currency,
  onNews,
  onClose,
}: {
  sel: BarSel;
  currency: string;
  onNews: () => void;
  onClose: () => void;
}) {
  const hasNews = !!sel.event && sel.event.news.length > 0;
  return (
    <div
      className="absolute top-2 left-2 z-10 card p-2.5 text-xs"
      style={{ width: 210, background: "var(--surface)", boxShadow: "0 4px 16px rgba(0,0,0,0.18)" }}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className="font-semibold" style={{ color: "var(--text)" }}>{sel.date}</span>
        <ChangeBadge pct={sel.pct} size="sm" />
        <button onClick={onClose} className="ml-auto px-1" style={{ color: "var(--muted)" }} aria-label="닫기">
          ✕
        </button>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 tabular-nums">
        <Row label="시가" value={fmtPrice(sel.o, currency)} />
        <Row label="고가" value={fmtPrice(sel.h, currency)} />
        <Row label="저가" value={fmtPrice(sel.l, currency)} />
        <Row label="종가" value={fmtPrice(sel.c, currency)} />
      </dl>
      <div className="mt-1.5 pt-1.5 border-t flex justify-between" style={{ borderColor: "var(--border)", color: "var(--muted)" }}>
        <span>거래량</span>
        <span className="tabular-nums" style={{ color: "var(--text)" }}>{fmtVolume(sel.v)}</span>
      </div>
      {sel.event && (
        <div className="mt-2">
          <div className="text-xs mb-1.5 leading-snug" style={{ color: "var(--text)" }}>
            📌 {sel.event.headline}
          </div>
          {hasNews ? (
            <button
              onClick={onNews}
              className="w-full py-1.5 rounded-lg text-xs font-medium transition"
              style={{ background: "var(--accent)", color: "#fff" }}
            >
              📰 이 날 뉴스 {sel.event.news.length}건 보기
            </button>
          ) : (
            <button
              onClick={onNews}
              className="w-full py-1.5 rounded-lg text-xs font-medium border transition"
              style={{ borderColor: "var(--border)", color: "var(--muted)" }}
            >
              해설 보기
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt style={{ color: "var(--muted)" }}>{label}</dt>
      <dd style={{ color: "var(--text)" }}>{value}</dd>
    </div>
  );
}
