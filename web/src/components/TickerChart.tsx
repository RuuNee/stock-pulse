import { useEffect, useRef } from "react";
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

interface Props {
  detail: TickerDetail;
  range: number; // trading days to show
  showMarkers: boolean;
  showMA: boolean;
  onMarkerClick: (event: ChartEvent) => void;
}

function toTime(dateStr: string): UTCTimestamp {
  return (Date.parse(dateStr + "T00:00:00Z") / 1000) as UTCTimestamp;
}

export default function TickerChart({ detail, range, showMarkers, showMA, onMarkerClick }: Props) {
  const holder = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const s = useSettings();

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
        color:
          (r[4] as number) >= (r[1] as number)
            ? `${upC}55`
            : `${downC}55`,
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

    // --- event markers ---
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

      chart.subscribeClick((param) => {
        if (!param.time) return;
        const clicked = (param.time as number) as UTCTimestamp;
        // find the event nearest the clicked time
        let best: ChartEvent | null = null;
        let bestDelta = Infinity;
        for (const e of events) {
          const d = Math.abs(toTime(e.date) - clicked);
          if (d < bestDelta) {
            bestDelta = d;
            best = e;
          }
        }
        if (best && bestDelta <= 3 * 86400) onMarkerClick(best);
      });
    }

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.code, range, showMarkers, showMA, s.beginner, s.theme, s.colorMode]);

  return <div ref={holder} className="w-full" style={{ height: "min(52vh, 460px)", minHeight: 260 }} />;
}
