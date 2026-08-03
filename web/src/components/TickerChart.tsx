import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
  LineStyle,
  type IChartApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { ChartEvent, TickerDetail } from "../lib/types";
import { useSettings } from "../lib/settings";
import { INDICATOR, type IndicatorStyle } from "../lib/signals";
import { fmtPrice, fmtVolume } from "../lib/format";
import ChangeBadge from "./ChangeBadge";
import Legend from "./LineSwatch";

/** 차트에 겹쳐 그릴 것들. 전부 끄면 순수 캔들만 남는다. */
export interface Overlays {
  markers: boolean; // 뉴스 마커
  ma: boolean; // 이동평균선
  bb: boolean; // 볼린저밴드
  macd: boolean; // MACD 보조 패널
  rsi: boolean; // RSI 보조 패널
  levels: boolean; // 지지·저항 가격선
}

interface Props {
  detail: TickerDetail;
  range: number; // trading days to show
  overlays: Overlays;
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

// pane 높이는 픽셀이 아니라 **비율**로 정해진다. `pane.setHeight(110)` 은 다음
// pane 이 추가되는 순간 재분배돼 무시된 것처럼 보인다(실제로 MACD 패널이 27px 로
// 찌그러졌다). 아래 값을 stretch factor 로 넘겨 비율을 잡고, 컨테이너 높이도 같은
// 만큼 키워서 가격 패널의 절대 크기가 유지되게 한다.
const MAIN_PANE_PX = 400;
const MACD_PANE_PX = 110;
const RSI_PANE_PX = 90;

function toTime(dateStr: string): UTCTimestamp {
  return (Date.parse(dateStr + "T00:00:00Z") / 1000) as UTCTimestamp;
}

const MA_KEYS = ["ma5", "ma20", "ma60", "ma120"] as (keyof typeof INDICATOR)[];

export default function TickerChart({ detail, range, overlays, onEventNews }: Props) {
  const holder = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const s = useSettings();
  const [sel, setSel] = useState<BarSel | null>(null);

  // Clear the detail panel whenever the chart is rebuilt (range/mode change).
  useEffect(() => setSel(null), [detail.code, range]);

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
        panes: { separatorColor: dark ? "#263449" : "#dbe3ef", separatorHoverColor: "#6366f155" },
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
    const ind = detail.indicators ?? {};

    /** 지표 배열(전체 길이)을 현재 구간에 맞춰 잘라 라인 데이터로. */
    const lineData = (key: string) =>
      slice
        .map((r, i) => ({ time: toTime(r[0] as string), value: ind[key]?.[startIdx + i] }))
        .filter((p): p is { time: UTCTimestamp; value: number } => p.value != null);

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

    // --- price: candles ---
    const priceSeries = chart.addSeries(CandlestickSeries, {
      upColor: upC,
      downColor: downC,
      borderUpColor: upC,
      borderDownColor: downC,
      wickUpColor: upC,
      wickDownColor: downC,
    });
    priceSeries.setData(
      slice.map((r) => ({
        time: toTime(r[0] as string),
        open: r[1] as number,
        high: r[2] as number,
        low: r[3] as number,
        close: r[4] as number,
      })),
    );

    // --- moving averages ---
    if (overlays.ma) {
      for (const key of MA_KEYS) {
        if (!ind[key]) continue;
        const maLine = chart.addSeries(LineSeries, {
          color: INDICATOR[key].color,
          lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        });
        maLine.setData(lineData(key));
      }
    }

    // --- 볼린저밴드: 위·아래 선만 그린다. 중심선은 20일선과 같은 값이라
    //     이동평균을 켠 상태에서 겹쳐 그리면 화면만 지저분해진다. ---
    if (overlays.bb && ind.bbUpper && ind.bbLower) {
      for (const key of ["bbUpper", "bbLower"]) {
        const band = chart.addSeries(LineSeries, {
          color: `${INDICATOR.bb.color}99`,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        band.setData(lineData(key));
      }
    }

    // --- 지지·저항: 분석이 잡아낸 기준선을 가로줄로 ---
    if (overlays.levels && detail.analysis) {
      const { support, resistance } = detail.analysis.levels;
      if (support != null) {
        priceSeries.createPriceLine({
          price: support, color: upC, lineWidth: 1,
          lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "지지",
        });
      }
      if (resistance != null) {
        priceSeries.createPriceLine({
          price: resistance, color: downC, lineWidth: 1,
          lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "저항",
        });
      }
    }

    // --- 보조 패널: MACD / RSI. 가격과 단위가 달라 별도 pane 에 올린다. ---
    const paneWeights: number[] = [MAIN_PANE_PX];

    if (overlays.macd && ind.macd && ind.macdSignal) {
      const pane = chart.addPane();
      const idx = pane.paneIndex();
      const hist = chart.addSeries(
        HistogramSeries,
        { priceFormat: { type: "price", precision: 2, minMove: 0.01 }, priceLineVisible: false },
        idx,
      );
      hist.setData(
        lineData("macdHist").map((p) => ({
          ...p,
          color: p.value >= 0 ? `${upC}88` : `${downC}88`,
        })),
      );
      const macdLine = chart.addSeries(
        LineSeries,
        { color: INDICATOR.macd.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
        idx,
      );
      macdLine.setData(lineData("macd"));
      const sigLine = chart.addSeries(
        LineSeries,
        {
          color: INDICATOR.macdSignal.color, lineWidth: 1, lineStyle: LineStyle.Dashed,
          priceLineVisible: false, lastValueVisible: false,
        },
        idx,
      );
      sigLine.setData(lineData("macdSignal"));
      paneWeights.push(MACD_PANE_PX);
    }

    if (overlays.rsi && ind.rsi14) {
      const pane = chart.addPane();
      const idx = pane.paneIndex();
      const rsiLine = chart.addSeries(
        LineSeries,
        {
          color: INDICATOR.rsi.color, lineWidth: 1, priceLineVisible: false,
          priceFormat: { type: "price", precision: 0, minMove: 1 },
        },
        idx,
      );
      rsiLine.setData(lineData("rsi14"));
      for (const [level, color, title] of [[70, downC, "과매수"], [30, upC, "과매도"]] as const) {
        rsiLine.createPriceLine({
          price: level, color, lineWidth: 1,
          lineStyle: LineStyle.Dotted, axisLabelVisible: true, title,
        });
      }
      paneWeights.push(RSI_PANE_PX);
    }

    if (paneWeights.length > 1) {
      chart.panes().forEach((p, i) => p.setStretchFactor(paneWeights[i] ?? 1));
    }

    // --- event markers (visual hint only; click detail handled below) ---
    if (overlays.markers) {
      const firstDate = slice[0]?.[0] as string | undefined;
      const events = detail.events.filter((e) => !firstDate || e.date >= firstDate);
      // Shape-only markers (no text): text labels overlap when events are
      // dense and — because lightweight-charts hides colliding labels — make
      // markers vanish when zoomed in. Meaning comes from the legend below and
      // the click-to-detail panel. Size scales gently with severity.
      const markers: SeriesMarker<Time>[] = events.map((e) => {
        const positive = e.changePct >= 0;
        return {
          time: toTime(e.date),
          position: positive ? "aboveBar" : "belowBar",
          color: e.type === "volumeSpike" ? "#f59e0b" : positive ? upC : downC,
          shape: e.type === "volumeSpike" ? "circle" : positive ? "arrowUp" : "arrowDown",
          size: e.severity >= 3 ? 2 : 1,
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
  }, [
    detail.code, range, s.theme, s.colorMode,
    overlays.markers, overlays.ma, overlays.bb, overlays.macd, overlays.rsi, overlays.levels,
  ]);

  const upC = s.colorMode === "kr" ? "#e11d48" : "#16a34a";
  const downC = s.colorMode === "kr" ? "#2563eb" : "#dc2626";
  const extra = (overlays.macd ? MACD_PANE_PX : 0) + (overlays.rsi ? RSI_PANE_PX : 0);

  const priceLegend: IndicatorStyle[] = [
    ...(overlays.ma ? MA_KEYS.map((k) => INDICATOR[k]) : []),
    ...(overlays.bb ? [INDICATOR.bb] : []),
  ];

  return (
    <div className="relative w-full">
      <div
        ref={holder}
        className="w-full"
        style={{ height: `calc(min(52vh, 460px) + ${extra}px)`, minHeight: 260 + extra }}
      />
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
      {/* 켠 지표의 **색 견본**. 이름만 적으면 초보가 화면의 어느 선인지 못 찾는다. */}
      <Legend items={priceLegend} title="가격" className="mt-2 px-1" />
      {overlays.macd && (
        <Legend items={[INDICATOR.macd, INDICATOR.macdSignal]} title="MACD 패널" className="mt-1 px-1" />
      )}
      {overlays.rsi && <Legend items={[INDICATOR.rsi]} title="RSI 패널" className="mt-1 px-1" />}
      {overlays.markers && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 px-1 text-[11px]" style={{ color: "var(--muted)" }}>
          <span style={{ color: upC }}>▲ 급등</span>
          <span style={{ color: downC }}>▼ 급락</span>
          <span style={{ color: "#f59e0b" }}>● 거래량 급증</span>
          <span>· 마커나 봉을 누르면 그날 상세·뉴스</span>
        </div>
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
