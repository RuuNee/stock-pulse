import { useSettings } from "../lib/settings";
import { verdictColor, type IndicatorStyle } from "../lib/signals";
import Legend from "./LineSwatch";
import type { Verdict } from "../lib/types";

/** 도움말용 예시 차트.
 *
 *  캡처 이미지를 쓰지 않는다 — 이미지는 다크/라이트 테마에 따라 어색해지고,
 *  화면 폭에 따라 글씨가 뭉개지며, 지표 색이 실제 차트와 어긋나면 오히려
 *  헷갈린다. 대신 값을 그대로 SVG 로 그려서 실제 종목 차트와 같은 색을 쓴다.
 *
 *  **캔들로 그린다.** 종가만 이은 선은 "봉을 어떻게 읽는가"를 설명하는 페이지의
 *  그림으로는 앞뒤가 맞지 않는다. 다만 캔들은 폭이 필요해서, 지표는 긴 시리즈로
 *  계산하고 **마지막 `visible` 봉만 그린다** — 실제 종목 차트가 기간 칩으로
 *  하는 일과 같다. 그래야 60일선이 화면 왼쪽 끝부터 살아 있으면서도 봉 하나가
 *  읽을 수 있는 굵기로 나온다.
 */

export interface GuideSeries {
  points: (number | null)[];
  color: string;
  dash?: boolean;
  width?: number;
  /** 주면 차트 아래 색 견본 범례에 오른다. */
  label?: string;
}

export interface GuideMarker {
  i: number;
  tone: Verdict;
  label: string;
}

export interface GuideLine {
  value: number;
  color: string;
  label?: string;
}

export interface GuideSub {
  series?: GuideSeries[];
  bars?: (number | null)[];
  lines?: GuideLine[];
  min?: number;
  max?: number;
}

export interface Bar {
  o: number;
  h: number;
  l: number;
  c: number;
}

interface Props {
  price: number[];
  overlays?: GuideSeries[];
  band?: { upper: (number | null)[]; lower: (number | null)[]; color: string; label?: string };
  hlines?: GuideLine[];
  markers?: GuideMarker[];
  volume?: number[];
  sub?: GuideSub;
  /** 마지막 N봉만 그린다 (지표 계산은 전체 시리즈로 이미 끝난 상태). */
  visible?: number;
  /** 종가 선으로 그리고 싶을 때만 false. 기본은 캔들. */
  candles?: boolean;
}

const W = 320;
const H_MAIN = 150;
const H_SUB = 52;
const PAD_X = 7;
const PAD_Y = 18; // 마커 삼각형과 가로선 라벨이 잘리지 않을 만큼

export default function PatternChart({
  price, overlays = [], band, hlines = [], markers = [], volume, sub,
  visible, candles = true,
}: Props) {
  const s = useSettings();

  // --- 보이는 구간만 잘라 낸다 (지표 배열도 같은 자리에서) ---
  const start = Math.max(0, price.length - (visible ?? price.length));
  const cut = <T,>(a: T[] | undefined) => (a ? a.slice(start) : undefined);
  const px = price.slice(start);
  const n = px.length;

  const bars = toBars(price).slice(start);
  const view = {
    overlays: overlays.map((o) => ({ ...o, points: o.points.slice(start) })),
    band: band && {
      ...band,
      upper: band.upper.slice(start),
      lower: band.lower.slice(start),
    },
    volume: cut(volume),
    markers: markers
      .map((m) => ({ ...m, i: m.i - start }))
      .filter((m) => m.i >= 0 && m.i < n),
    sub: sub && {
      ...sub,
      series: sub.series?.map((ss) => ({ ...ss, points: ss.points.slice(start) })),
      bars: cut(sub.bars),
    },
  };

  const height = H_MAIN + (sub ? H_SUB + 6 : 0);

  // 세로 눈금은 그려지는 모든 값을 담아야 한다 (꼬리와 밴드가 종가 밖으로 나간다).
  const pool: number[] = candles ? bars.flatMap((b) => [b.h, b.l]) : [...px];
  for (const o of view.overlays) pool.push(...(o.points.filter((v) => v != null) as number[]));
  if (view.band) {
    pool.push(...(view.band.upper.filter((v) => v != null) as number[]));
    pool.push(...(view.band.lower.filter((v) => v != null) as number[]));
  }
  for (const l of hlines) pool.push(l.value);

  const lo = Math.min(...pool);
  const hi = Math.max(...pool);
  const span = hi - lo || 1;
  const x = (i: number) => PAD_X + (i * (W - PAD_X * 2)) / Math.max(1, n - 1);
  const y = (v: number) => PAD_Y + (1 - (clamp(v, lo, hi) - lo) / span) * (H_MAIN - PAD_Y * 2);

  const path = (pts: (number | null)[]) => {
    let d = "";
    let pen = false;
    pts.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
      pen = true;
    });
    return d.trim();
  };

  // --- 보조 패널 스케일 ---
  const subTop = H_MAIN + 6;
  const subPool: number[] = [];
  if (view.sub) {
    for (const ss of view.sub.series ?? []) subPool.push(...(ss.points.filter((v) => v != null) as number[]));
    if (view.sub.bars) subPool.push(...(view.sub.bars.filter((v) => v != null) as number[]));
    for (const l of view.sub.lines ?? []) subPool.push(l.value);
  }
  const sLo = view.sub?.min ?? (subPool.length ? Math.min(...subPool) : 0);
  const sHi = view.sub?.max ?? (subPool.length ? Math.max(...subPool) : 1);
  const sSpan = sHi - sLo || 1;
  // min/max 를 직접 준 패널(RSI 10~90 등)은 값이 그 밖으로 나갈 수 있다. 클램프하지
  // 않으면 선이 패널을 뚫고 가격 차트 위로 그려진다.
  const sy = (v: number) => subTop + 5 + (1 - (clamp(v, sLo, sHi) - sLo) / sSpan) * (H_SUB - 10);
  const subPath = (pts: (number | null)[]) => {
    let d = "";
    let pen = false;
    pts.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${sy(v).toFixed(1)} `;
      pen = true;
    });
    return d.trim();
  };

  const slot = (W - PAD_X * 2) / Math.max(1, n - 1);
  const bodyW = Math.max(2, slot * 0.62);
  const volMax = view.volume ? Math.max(...view.volume) || 1 : 1;

  // 이름이 붙은 선만 색 견본으로 내보낸다 (가로선은 차트 안에 라벨이 이미 있다).
  // 가격 패널과 보조 패널을 갈라 둔다 — RSI·%K 가 20일선과 같은 보라라, 한 줄에
  // 늘어놓으면 서로 관련 있는 선처럼 보인다.
  const priceLegend: IndicatorStyle[] = [
    ...overlays.filter((o) => o.label).map((o) => ({ color: o.color, label: o.label!, dash: o.dash })),
    ...(band?.label ? [{ color: band.color, label: band.label, dash: true }] : []),
  ];
  const subLegend: IndicatorStyle[] = (sub?.series ?? [])
    .filter((ss) => ss.label)
    .map((ss) => ({ color: ss.color, label: ss.label!, dash: ss.dash }));

  const chart = (
    <svg
      viewBox={`0 0 ${W} ${height}`}
      width="100%"
      style={{ height: "auto", display: "block", borderRadius: 10, background: "var(--surface-2)" }}
      role="img"
    >
      {/* 마커 위치를 세로줄로 먼저 깔아 둔다 (봉 아래에) */}
      {view.markers.map((m, k) => (
        <line
          key={`vl${k}`} x1={x(m.i)} x2={x(m.i)} y1={2} y2={height - 2}
          stroke={verdictColor(m.tone, s)} strokeWidth={1} strokeDasharray="2 3" opacity={0.5}
        />
      ))}

      {/* 볼린저 같은 통로는 면으로 채워야 '통로'로 읽힌다 */}
      {view.band && (
        <>
          <path d={areaPath(view.band.upper, view.band.lower, x, y)} fill={view.band.color} opacity={0.1} stroke="none" />
          <path d={path(view.band.upper)} fill="none" stroke={view.band.color} strokeWidth={1} strokeDasharray="3 2" />
          <path d={path(view.band.lower)} fill="none" stroke={view.band.color} strokeWidth={1} strokeDasharray="3 2" />
        </>
      )}

      {hlines.map((l, k) => (
        <g key={`hl${k}`}>
          <line x1={PAD_X} x2={W - PAD_X} y1={y(l.value)} y2={y(l.value)}
                stroke={l.color} strokeWidth={1} strokeDasharray="4 3" opacity={0.85} />
          {l.label && (
            <text x={W - PAD_X} y={y(l.value) - 3.5} textAnchor="end" fontSize={8} fill={l.color}>
              {l.label}
            </text>
          )}
        </g>
      ))}

      {view.volume && view.volume.map((v, i) => (
        <rect
          key={`v${i}`} x={x(i) - bodyW / 2} width={bodyW}
          y={H_MAIN - PAD_Y / 2 - (v / volMax) * 26} height={(v / volMax) * 26}
          fill={bars[i] && bars[i].c >= bars[i].o ? s.upColor : s.downColor} opacity={0.3}
        />
      ))}

      {view.overlays.map((o, k) => (
        <path
          key={`o${k}`} d={path(o.points)} fill="none" stroke={o.color}
          strokeWidth={o.width ?? 1.3} strokeDasharray={o.dash ? "3 2" : undefined}
          strokeLinejoin="round"
        />
      ))}

      {candles
        ? bars.map((b, i) => {
            const up = b.c >= b.o;
            const color = up ? s.upColor : s.downColor;
            const cx = x(i);
            const top = Math.min(y(b.o), y(b.c));
            const h = Math.max(1, Math.abs(y(b.c) - y(b.o)));
            return (
              <g key={`c${i}`}>
                <line x1={cx} x2={cx} y1={y(b.h)} y2={y(b.l)} stroke={color} strokeWidth={0.9} />
                <rect x={cx - bodyW / 2} width={bodyW} y={top} height={h} fill={color} />
              </g>
            );
          })
        : <path d={path(px)} fill="none" stroke="var(--text)" strokeWidth={1.6} strokeLinejoin="round" />}

      {/* 마커는 봉을 가리지 않게 위/아래로 비켜 세운 삼각형 (실제 차트와 같은 규칙) */}
      {view.markers.map((m, k) => {
        const b = bars[m.i];
        if (!b) return null;
        const color = verdictColor(m.tone, s);
        const cx = x(m.i);
        if (m.tone === "neutral") {
          return <circle key={`m${k}`} cx={cx} cy={y(b.c)} r={3.2} fill={color}
                         stroke="var(--surface)" strokeWidth={1.2} />;
        }
        const up = m.tone === "bullish";
        const tip = up ? y(b.l) + 5 : y(b.h) - 5;
        const base = up ? tip + 6.5 : tip - 6.5;
        return (
          <polygon key={`m${k}`} points={`${cx},${tip} ${cx - 4},${base} ${cx + 4},${base}`}
                   fill={color} />
        );
      })}

      {view.sub && (
        <>
          <line x1={PAD_X} x2={W - PAD_X} y1={subTop} y2={subTop} stroke="var(--border)" strokeWidth={1} />
          {(view.sub.lines ?? []).map((l, k) => (
            <g key={`sl${k}`}>
              <line x1={PAD_X} x2={W - PAD_X} y1={sy(l.value)} y2={sy(l.value)}
                    stroke={l.color} strokeWidth={1} strokeDasharray="2 3" opacity={0.85} />
              {l.label && (
                <text x={PAD_X + 1} y={sy(l.value) - 2} fontSize={7.5} fill={l.color}>{l.label}</text>
              )}
            </g>
          ))}
          {view.sub.bars && view.sub.bars.map((v, i) =>
            v == null ? null : (
              <rect key={`sb${i}`} x={x(i) - bodyW / 2} width={bodyW}
                    y={Math.min(sy(v), sy(0))} height={Math.max(1, Math.abs(sy(v) - sy(0)))}
                    fill={v >= 0 ? s.upColor : s.downColor} opacity={0.55} />
            ))}
          {(view.sub.series ?? []).map((ss, k) => (
            <path key={`ss${k}`} d={subPath(ss.points)} fill="none" stroke={ss.color}
                  strokeWidth={ss.width ?? 1.3} strokeDasharray={ss.dash ? "3 2" : undefined} />
          ))}
        </>
      )}
    </svg>
  );

  if (!priceLegend.length && !subLegend.length) return chart;
  return (
    <div className="flex flex-col gap-1">
      {chart}
      <Legend items={priceLegend} className="px-1 mt-0.5" />
      <Legend items={subLegend} title="보조 패널" className="px-1" />
    </div>
  );
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** 결정론적 잔떨림. 난수를 쓰면 새로고침마다 봉 모양이 달라진다. */
const jitter = (t: number) => Math.sin(t) * 0.7 + Math.cos(t * 1.9) * 0.3;

/** 종가 배열 → 캔들. 시가는 전일 종가 근처에서 출발하고, 꼬리는 그 종목의
 *  평균 일간 변동폭에 비례해 붙인다. 지표 계산은 전부 **종가**로 하므로
 *  (실제 파이프라인과 같다) 여기서 만든 시·고·저는 그림에만 쓰인다. */
export function toBars(closes: number[]): Bar[] {
  const moves = closes.slice(1).map((c, i) => Math.abs(c - closes[i]));
  const step = moves.length ? moves.reduce((a, b) => a + b, 0) / moves.length : 1;
  return closes.map((c, i) => {
    const prev = i === 0 ? c : closes[i - 1];
    const o = prev + step * 0.5 * jitter(i * 2.1);
    return {
      o,
      c,
      h: Math.max(o, c) + step * (0.2 + 0.5 * Math.abs(jitter(i * 1.3))),
      l: Math.min(o, c) - step * (0.2 + 0.5 * Math.abs(jitter(i * 0.7))),
    };
  });
}

/** 위·아래 선 사이를 닫힌 다각형으로 (윗선 →, 아랫선 ←). */
function areaPath(
  upper: (number | null)[],
  lower: (number | null)[],
  x: (i: number) => number,
  y: (v: number) => number,
): string {
  const idx = upper
    .map((v, i) => (v != null && lower[i] != null ? i : -1))
    .filter((i) => i >= 0);
  if (idx.length < 2) return "";
  const top = idx.map((i) => `${x(i).toFixed(1)} ${y(upper[i] as number).toFixed(1)}`).join(" L");
  const bottom = [...idx].reverse()
    .map((i) => `${x(i).toFixed(1)} ${y(lower[i] as number).toFixed(1)}`).join(" L");
  return `M${top} L${bottom} Z`;
}

/** 캔들 하나를 뜯어 보는 그림 — "빨간 봉/파란 봉"이 무슨 뜻인지부터. */
export function CandleAnatomy() {
  const s = useSettings();
  const box = (cx: number, color: string, up: boolean) => (
    <g>
      <line x1={cx} x2={cx} y1={14} y2={104} stroke={color} strokeWidth={1.4} />
      <rect x={cx - 11} y={up ? 38 : 34} width={22} height={44} fill={color} rx={1.5} />
      <text x={cx} y={10} textAnchor="middle" fontSize={8} fill="var(--muted)">고가</text>
      <text x={cx} y={114} textAnchor="middle" fontSize={8} fill="var(--muted)">저가</text>
      <text x={cx + 15} y={up ? 41 : 79} fontSize={8} fill="var(--muted)">종가</text>
      <text x={cx + 15} y={up ? 85 : 39} fontSize={8} fill="var(--muted)">시가</text>
    </g>
  );
  return (
    <svg viewBox="0 0 320 130" width="100%"
         style={{ height: "auto", display: "block", borderRadius: 10, background: "var(--surface-2)" }}
         role="img">
      {box(70, s.upColor, true)}
      <text x={70} y={128} textAnchor="middle" fontSize={9} fill={s.upColor} fontWeight="bold">
        오른 날 (양봉)
      </text>
      {box(220, s.downColor, false)}
      <text x={220} y={128} textAnchor="middle" fontSize={9} fill={s.downColor} fontWeight="bold">
        내린 날 (음봉)
      </text>
    </svg>
  );
}
