// 도움말 > 차트분석 탭의 내용.
//
// 여기 실린 11가지는 pipeline/analyze/technical.py 가 실제로 판정하는 기법과
// 1:1로 맞춰져 있다. 종목 화면의 "기법별 판정" 줄을 보고 여기로 오면 같은
// 이름이 나와야 한다 — 이름이 어긋나면 도움말이 아니라 혼란이 된다.
//
// 예시 차트는 캡처가 아니라 아래 값 배열을 그대로 SVG 로 그린 것이다. 이동평균·
// 볼린저·RSI·MACD 도 실제 공식으로 계산해서 그린다 (아래 헬퍼). 그래야 "예시니까
// 대충 그린 그림"이 아니라 정말 그 모양이 나오는지 눈으로 확인된다.

import { INDICATOR, type IndicatorStyle } from "./signals";

// ---------------------------------------------------------------- 지표 계산
const seq = (n: number, f: (i: number) => number): number[] =>
  Array.from({ length: n }, (_, i) => f(i));

/** 결정론적인 잔물결 — 난수를 쓰면 새로고침마다 그림이 달라진다. */
const wob = (i: number, amp = 1) =>
  (Math.sin(i * 1.7) * 0.6 + Math.cos(i * 0.9) * 0.4 + Math.sin(i * 0.37) * 0.3) * amp;

export function sma(values: number[], n: number): (number | null)[] {
  return values.map((_, i) =>
    i < n - 1 ? null : values.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n,
  );
}

function ema(values: number[], n: number): number[] {
  const k = 2 / (n + 1);
  const out: number[] = [];
  values.forEach((v, i) => out.push(i === 0 ? v : v * k + out[i - 1] * (1 - k)));
  return out;
}

export function bollinger(values: number[], n = 20, mult = 2) {
  const mid = sma(values, n);
  const upper: (number | null)[] = [];
  const lower: (number | null)[] = [];
  values.forEach((_, i) => {
    const m = mid[i];
    if (m == null) { upper.push(null); lower.push(null); return; }
    const win = values.slice(i - n + 1, i + 1);
    const sd = Math.sqrt(win.reduce((a, b) => a + (b - m) ** 2, 0) / n);
    upper.push(m + mult * sd);
    lower.push(m - mult * sd);
  });
  return { mid, upper, lower };
}

export function rsi(values: number[], n = 14): (number | null)[] {
  let gain = 0;
  let loss = 0;
  const out: (number | null)[] = [null];
  for (let i = 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    gain = (gain * (n - 1) + Math.max(0, d)) / n;
    loss = (loss * (n - 1) + Math.max(0, -d)) / n;
    out.push(i < n ? null : loss === 0 ? 100 : 100 - 100 / (1 + gain / loss));
  }
  return out;
}

export function macd(values: number[], fast = 12, slow = 26, signal = 9) {
  const f = ema(values, fast);
  const s = ema(values, slow);
  const line = values.map((_, i) => f[i] - s[i]);
  const sig = ema(line, signal);
  return { line, signal: sig, hist: line.map((v, i) => v - sig[i]) };
}

/** 예시용 스토캐스틱. 도움말 그림에는 고가·저가 배열이 없어 종가 범위로 대신한다
 *  (모양은 같고, 파이프라인 쪽은 진짜 고·저를 쓴다). */
export function stochastic(values: number[], n = 14, smooth = 3) {
  const raw = values.map((v, i) => {
    if (i < n - 1) return null;
    const win = values.slice(i - n + 1, i + 1);
    const lo = Math.min(...win);
    const hi = Math.max(...win);
    return hi === lo ? 50 : ((v - lo) / (hi - lo)) * 100;
  });
  const roll = (src: (number | null)[]): (number | null)[] =>
    src.map((_, i) => {
      const win = src.slice(Math.max(0, i - smooth + 1), i + 1);
      if (win.length < smooth || win.some((x) => x == null)) return null;
      return (win as number[]).reduce((a, b) => a + b, 0) / win.length;
    });
  const k = roll(raw);
  return { k, d: roll(k) };
}

// 색은 `lib/signals.ts` 의 INDICATOR 한 곳에서만 정의한다 — 종목 차트와 도움말이
// 같은 상수를 봐야 "주황이 5일선"이라는 설명이 화면과 어긋나지 않는다.
const MA_STYLE: Record<number, IndicatorStyle> = {
  5: INDICATOR.ma5, 20: INDICATOR.ma20, 60: INDICATOR.ma60, 120: INDICATOR.ma120,
};

// ---------------------------------------------------------------- 예시 가격
//
// 시리즈는 길게(N=130) 만들고 그림은 마지막 VIS=55봉만 그린다.
//   · 길이가 필요한 이유 — 60일선은 60봉을 먹고 나서야 시작한다. 짧은 시리즈를
//     그대로 그리면 60일선이 화면 오른쪽 3분의 1에만 나타나 설명이 어그러진다.
//   · 그림을 자르는 이유 — 캔들은 폭이 필요하다. 130봉을 다 그리면 봉 하나가
//     2px짜리 실선이 돼서 "봉 읽는 법"을 설명하는 페이지에 캔들을 넣은 의미가 없다.
// 실제 종목 차트가 기간 칩(1개월/3개월…)으로 하는 일과 정확히 같다.
const N = 130;
export const VIS = 55;

/** 그림에 실제로 보이는 구간만. 지지·저항선 값을 여기서 뽑는다. */
const shown = (p: number[]) => p.slice(N - VIS);

const P = {
  // 꾸준한 상승 — 정배열
  up: seq(N, (i) => 100 + i * 0.7 + Math.sin(i / 7) * 6 + wob(i, 2)),
  // 꾸준한 하락 — 역배열
  down: seq(N, (i) => 190 - i * 0.7 + Math.sin(i / 7) * 6 + wob(i, 2)),
  // 내려오다 반등 — 골든크로스가 보이는 구간에서 나도록 전환점을 62에 둔다
  golden: seq(N, (i) =>
    (i < 62 ? 170 - i * 0.9 : 114.2 + (i - 62) * 1.15) + Math.sin(i / 5) * 3 + wob(i, 1.8)),
  // 오르다 꺾임 — 데드크로스
  dead: seq(N, (i) =>
    (i < 62 ? 110 + i * 0.9 : 165.8 - (i - 62) * 1.0) + Math.sin(i / 5) * 3 + wob(i, 1.8)),
  // MACD 전용. `golden` 은 전환점이 62라 MACD(12/26)의 상향 교차가 70 근처에서
  // 끝나 버린다 — 보이는 구간(75~129) 밖이라 정작 설명할 교차가 안 보였다.
  // MACD 는 이동평균 크로스보다 빨리 반응하므로 전환점을 뒤로 미룬다.
  macdTurn: seq(N, (i) =>
    (i < 92 ? 170 - i * 0.75 : 101 + (i - 92) * 1.5) + Math.sin(i / 5) * 3 + wob(i, 1.8)),
  // 완만하다 막판 급등 — 이격 과대
  spike: seq(N, (i) =>
    (i < 108 ? 120 + Math.sin(i / 9) * 5 : 120 + (i - 108) * 4.2) + wob(i, 1.5)),
  // 박스권 → 위로 돌파
  breakout: seq(N, (i) =>
    (i < 110 ? 125 + Math.sin(i / 6) * 8 : 133 + (i - 110) * 2.4) + wob(i, 1.5)),
  // 위아래로 오가는 박스권 — 지지·저항
  box: seq(N, (i) => 130 + Math.sin(i / 4.5) * 15 + wob(i, 1.8)),
  // 변동성 수축 후 확장 — 볼린저 스퀴즈
  squeeze: seq(N, (i) =>
    (i < 108
      ? 130 + Math.sin(i / 3) * Math.max(1.5, 9 - Math.max(0, i - 70) * 0.18)
      : 130 + (i - 108) * 2.2) + wob(i, 0.8)),
  // 과열 → 조정 → 침체 → 반등 (RSI용)
  swing: seq(N, (i) => 130 + Math.sin(i / 9) * 24 + Math.sin(i / 3) * 4 + wob(i, 1.2)),
  // 스토캐스틱 전용. `swing` 처럼 매끈한 파형에서는 14일 고·저 범위를 추세가
  // 독점해 %K 가 0/100 에 눌어붙고 그림이 사각파가 된다. 단기 진폭을 키워
  // 실제로 %K·%D 가 중간대를 오가며 교차하게 만든다.
  choppy: seq(N, (i) => 130 + Math.sin(i / 8) * 13 + Math.sin(i / 2.4) * 7 + wob(i, 2.6)),
};

/** `fast` 가 `slow` 를 마지막으로 교차한 지점. 마커 위치를 눈대중으로 박아 두면
 *  파형을 조금만 손봐도 점선이 엉뚱한 데 찍힌다 — 계산해서 쓴다. */
function crossIndex(fast: (number | null)[], slow: (number | null)[], dir: "up" | "down"): number {
  for (let i = fast.length - 1; i > 0; i--) {
    const a = fast[i], b = slow[i], pa = fast[i - 1], pb = slow[i - 1];
    if (a == null || b == null || pa == null || pb == null) continue;
    if (dir === "up" ? pa <= pb && a > b : pa >= pb && a < b) return i;
  }
  return -1;
}

/** `level` 을 처음 넘어선 지점 (돌파 마커용). */
function firstAbove(price: number[], level: number, from = 0): number {
  for (let i = from; i < price.length; i++) if (price[i] > level) return i;
  return price.length - 1;
}

export interface GuideItem {
  key: string; // technical.py 의 signal key 와 동일
  name: string; // 종목 화면 "기법별 판정"에 뜨는 이름
  group: string;
  what: string; // 무엇을 재는가
  read: { tone: "bullish" | "bearish" | "neutral"; text: string }[]; // 어떻게 읽는가
  caveat: string; // 언제 틀리는가
  chart: ChartSpec;
}

/** 선에 `label` 을 주면 차트 아래 **색 견본 범례**에 오른다. 초보가 "주황이
 *  5일선"을 글로만 읽고는 화면에서 못 찾는다 — 견본을 실제로 그려 보여준다. */
type GuideLine = { points: (number | null)[]; color: string; dash?: boolean; label?: string };

export interface ChartSpec {
  price: number[];
  overlays?: GuideLine[];
  band?: { upper: (number | null)[]; lower: (number | null)[]; color: string; label?: string };
  hlines?: { value: number; color: string; label?: string }[];
  markers?: { i: number; tone: "bullish" | "bearish" | "neutral"; label: string }[];
  volume?: number[];
  sub?: {
    series?: GuideLine[];
    bars?: (number | null)[];
    lines?: { value: number; color: string; label?: string }[];
    min?: number;
    max?: number;
  };
  visible?: number;
  candles?: boolean;
  caption: string;
}

const MA = (p: number[], n: number) => ({ points: sma(p, n), ...MA_STYLE[n] });

export const CHART_GUIDE: GuideItem[] = [
  {
    key: "maAlign",
    name: "이동평균 배열 (정배열 · 역배열)",
    group: "추세",
    what: "5일·20일·60일 평균선이 어떤 순서로 놓였는지를 봅니다. 짧은 평균이 위에 있다는 건 최근 며칠이 지난 몇 달보다 비쌌다는 뜻입니다.",
    read: [
      { tone: "bullish", text: "5일선 > 20일선 > 60일선 = 정배열. 가장 안정적인 상승 형태로 봅니다." },
      { tone: "bearish", text: "5일선 < 20일선 < 60일선 = 역배열. 하락 추세가 자리 잡은 형태입니다." },
      { tone: "neutral", text: "선들이 뒤엉켜 있으면 방향을 정하지 못한 구간입니다." },
    ],
    caveat: "평균선은 지나간 값의 요약이라 방향이 바뀐 뒤에야 순서가 바뀝니다. 배열이 완성됐을 땐 이미 꽤 움직인 뒤인 경우가 많습니다.",
    chart: {
      price: P.up,
      overlays: [MA(P.up, 5), MA(P.up, 20), MA(P.up, 60)],
      caption: "빨간 봉(오른 날)이 이어지며, 주황 5일 · 보라 20일 · 하늘 60일선이 위에서부터 차례로 놓인 정배열",
    },
  },
  {
    key: "maCross",
    name: "골든크로스 · 데드크로스",
    group: "추세",
    what: "20일선이 60일선을 아래에서 위로 뚫으면 골든크로스, 위에서 아래로 뚫으면 데드크로스입니다. 추세가 바뀌는 지점을 한 점으로 표시해 줍니다.",
    read: [
      { tone: "bullish", text: "골든크로스 — 중기 추세가 위로 돌아섰다는 신호로 봅니다." },
      { tone: "bearish", text: "데드크로스 — 중기 추세가 아래로 꺾였다는 신호로 봅니다." },
    ],
    caveat: "횡보장에서는 두 선이 계속 엉키면서 크로스가 반복해서 나옵니다. 이때 신호를 그대로 따르면 계속 어긋납니다. 이 사이트는 최근 10거래일 안에 생긴 교차만 '발생'으로 봅니다.",
    chart: {
      price: P.golden,
      overlays: [MA(P.golden, 20), MA(P.golden, 60)],
      markers: [{
        i: crossIndex(sma(P.golden, 20), sma(P.golden, 60), "up"),
        tone: "bullish", label: "골든크로스",
      }],
      caption: "파란 봉(내린 날)이 이어지다 빨간 봉으로 바뀌고, 보라 20일선이 하늘 60일선을 아래에서 위로 통과하는 순간 (점선 위치)",
    },
  },
  {
    key: "disparity",
    name: "이격도 (20일선과의 거리)",
    group: "가격대",
    what: "지금 주가가 20일 평균에서 몇 % 떨어져 있는지 봅니다. 고무줄처럼, 너무 벌어지면 평균 쪽으로 되돌아오려는 힘이 커진다고 해석합니다.",
    read: [
      { tone: "bearish", text: "+12% 이상 — 단기 과열. 되돌림이 나오기 쉬운 자리로 봅니다." },
      { tone: "bullish", text: "-12% 이하 — 단기 낙폭 과대. 기술적 반등을 노리는 자리입니다." },
      { tone: "neutral", text: "±3% 이내 — 20일선에 붙은 상태. 추세가 살아 있으면 눌림목입니다." },
    ],
    caveat: "강한 상승장에서는 이격이 벌어진 채로 계속 오르기도 합니다. 이격만 보고 파는 건 위험하고, 추세와 같이 봐야 합니다.",
    chart: {
      price: P.spike,
      overlays: [MA(P.spike, 20)],
      markers: [{ i: N - 1, tone: "bearish", label: "20일선에서 크게 벌어짐" }],
      caption: "긴 빨간 봉이 연달아 서면서 보라 20일선과의 간격이 급격히 벌어진 상태 = 이격 과대",
    },
  },
  {
    key: "trendSlope",
    name: "중기 추세 (60일선 기울기)",
    group: "추세",
    what: "60일 평균선이 최근 20거래일 동안 몇 % 움직였는지로 큰 방향을 봅니다. 선이 서 있으면 추세, 누워 있으면 박스권입니다.",
    read: [
      { tone: "bullish", text: "+1% 이상 — 중기 방향이 위입니다." },
      { tone: "bearish", text: "-1% 이하 — 중기 방향이 아래입니다." },
      { tone: "neutral", text: "±1% 안 — 방향 없는 횡보로 봅니다." },
    ],
    caveat: "60일선은 반응이 느립니다. 하루 이틀의 급변은 이 기울기에 거의 나타나지 않습니다.",
    chart: {
      price: P.down,
      overlays: [MA(P.down, 60)],
      caption: "파란 봉이 우세한 가운데 하늘색 60일선이 꾸준히 아래를 향하는 중기 하락추세",
    },
  },
  {
    key: "macd",
    name: "MACD",
    group: "모멘텀",
    what: "12일 평균과 26일 평균의 차이(MACD)와, 그 차이의 9일 평균(시그널)을 비교합니다. 두 선의 간격을 막대로 그린 것이 히스토그램입니다.",
    read: [
      { tone: "bullish", text: "MACD가 시그널선을 위로 뚫으면(히스토그램이 0을 넘으면) 상승 쪽에 힘이 실린 신호." },
      { tone: "bearish", text: "아래로 뚫으면 상승 힘이 꺾인 신호로 봅니다." },
    ],
    caveat: "이동평균에서 나온 지표라 역시 후행합니다. 방향이 자주 바뀌는 종목에서는 교차 신호가 잦아 신뢰도가 떨어집니다.",
    chart: (() => {
      const m = macd(P.macdTurn);
      return {
        price: P.macdTurn,
        markers: [{
          i: crossIndex(m.line, m.signal, "up"), tone: "bullish" as const, label: "상향 교차",
        }],
        sub: {
          series: [
            { points: m.line, ...INDICATOR.macd },
            { points: m.signal, ...INDICATOR.macdSignal },
          ],
          bars: m.hist,
          lines: [{ value: 0, color: "var(--muted)" }],
        },
        caption: "아래 보조 패널 — 남색 MACD가 주황 시그널선을 위로 통과하는 지점(점선)에서 막대가 0 위로 올라선다",
      };
    })(),
  },
  {
    key: "rsi",
    name: "RSI (상대강도지수)",
    group: "모멘텀",
    what: "최근 14일 동안 오른 폭과 내린 폭의 비율을 0~100으로 나타냅니다. 얼마나 한쪽으로 쏠렸는지를 보는 지표입니다.",
    read: [
      { tone: "bearish", text: "70 이상 — 과매수. 너무 많이 올랐다고 보는 구간." },
      { tone: "bullish", text: "30 이하 — 과매도. 너무 많이 내렸다고 보는 구간." },
      { tone: "bullish", text: "50선을 위로 넘으면 매수세가 우위로 돌아섰다고 읽습니다." },
    ],
    caveat: "강세장에서는 RSI가 70 위에 몇 주씩 머무는 일이 흔합니다. '70이니까 판다'는 식으로 쓰면 상승분을 통째로 놓칩니다.",
    chart: {
      price: P.swing,
      sub: {
        series: [{ points: rsi(P.swing), ...INDICATOR.rsi }],
        lines: [
          { value: 70, color: "#dc2626", label: "70 과매수" },
          { value: 30, color: "#16a34a", label: "30 과매도" },
        ],
        min: 10,
        max: 90,
      },
      caption: "아래 보조 패널 — 보라 RSI가 위 점선(70) 위면 과열, 아래 점선(30) 밑이면 침체",
    },
  },
  {
    key: "bollinger",
    name: "볼린저밴드",
    group: "변동성",
    what: "20일 평균선 위아래로 표준편차 2배만큼 통로를 그립니다. 주가는 대체로 이 통로 안에서 움직이므로, 통로의 폭과 주가 위치로 상태를 읽습니다.",
    read: [
      { tone: "bullish", text: "위쪽 선에 붙어 움직이면 상승 흐름이 강한 상태." },
      { tone: "bearish", text: "아래쪽 선에 붙어 움직이면 하락 압력이 큰 상태." },
      { tone: "neutral", text: "통로가 좁아지면(스퀴즈) 곧 한쪽으로 크게 움직인다고 봅니다." },
    ],
    caveat: "밴드를 뚫었다고 바로 되돌아오지는 않습니다. 강한 추세에서는 밴드 자체가 따라 움직이며 이탈이 길게 이어집니다.",
    chart: (() => {
      const b = bollinger(P.squeeze);
      return {
        price: P.squeeze,
        band: { upper: b.upper, lower: b.lower, ...INDICATOR.bb },
        overlays: [{ points: b.mid, color: INDICATOR.ma20.color, dash: true, label: "20일선 (밴드 중심)" }],
        markers: [{ i: 106, tone: "neutral", label: "밴드 수축" }],
        caption: "봉이 짧아지며 초록 통로가 좁아졌다가(점선 위치), 방향이 나오면서 다시 벌어지는 모습",
      };
    })(),
  },
  {
    key: "stochastic",
    name: "스토캐스틱",
    group: "모멘텀",
    what: "최근 14일 고가~저가 범위에서 오늘 종가가 어디쯤 찍혔는지를 0~100으로 봅니다. 위쪽 끝에서 마감하면 매수세가 셌다는 뜻입니다.",
    read: [
      { tone: "bullish", text: "20 아래 침체 구간에서 %K가 %D를 위로 뚫으면 단기 반등 신호." },
      { tone: "bearish", text: "80 위 과열 구간에서 %K가 %D를 아래로 뚫으면 단기 조정 신호." },
    ],
    caveat: "RSI보다 더 자주 출렁여서 신호가 많이 나옵니다. 추세가 강할 땐 과열 신호를 무시하는 편이 나을 때도 있습니다.",
    chart: (() => {
      const st = stochastic(P.choppy);
      return {
        price: P.choppy,
        sub: {
          series: [
            { points: st.k, ...INDICATOR.stochK },
            { points: st.d, ...INDICATOR.stochD },
          ],
          lines: [
            { value: 80, color: "#dc2626", label: "80" },
            { value: 20, color: "#16a34a", label: "20" },
          ],
          min: 0,
          max: 100,
        },
        caption: "아래 보조 패널 — 보라 %K가 주황 %D를 뚫는 지점, 그리고 80/20 점선과의 위치를 본다",
      };
    })(),
  },
  {
    key: "volume",
    name: "거래량",
    group: "수급",
    what: "그날 사고팔린 주식 수를 20일 평균과 비교합니다. 가격이 '어디로' 갔는지와 '얼마나 많은 사람이 참여해서' 갔는지는 다른 정보입니다.",
    read: [
      { tone: "bullish", text: "오르면서 거래량이 평소의 1.5배 넘게 늘면 매수세가 실제로 붙은 것으로 봅니다." },
      { tone: "bearish", text: "내리면서 거래량이 급증하면 파는 쪽에 힘이 실린 것으로 봅니다." },
      { tone: "neutral", text: "거래량이 말라 있으면 관심이 식어 방향이 잘 나지 않습니다." },
    ],
    caveat: "배당락일, 지수 편입·편출, 만기일처럼 수급 이벤트로만 거래량이 튀는 날도 많습니다.",
    chart: {
      price: P.breakout,
      volume: seq(N, (i) => (i >= 108 ? 68 + wob(i, 12) : 22 + wob(i, 8))),
      markers: [{ i: 110, tone: "bullish", label: "거래량 급증" }],
      caption: "아래 막대가 거래량 — 빨간 봉으로 방향이 잡히는 구간에서 함께 커지고 있다",
    },
  },
  {
    key: "breakout",
    name: "신고가 돌파 · 신저가 이탈",
    group: "가격대",
    what: "최근 60거래일의 최고가를 넘었는지, 최저가를 밑돌았는지 봅니다. 흔히 말하는 '추격'과 '손절' 판단의 근거가 되는 자리입니다.",
    read: [
      { tone: "bullish", text: "60일 최고가 돌파 — 위에 매물벽이 없어 흐름이 이어지기 쉽다고 봅니다." },
      { tone: "bearish", text: "60일 최저가 이탈 — 아래에 받쳐 줄 가격대가 없어 낙폭이 커지기 쉽습니다." },
    ],
    caveat: "돌파했다가 곧바로 되밀리는 '속임수 돌파'가 자주 나옵니다. 거래량이 함께 늘었는지를 같이 보는 이유입니다.",
    chart: (() => {
      // 박스권 구간의 최고가를 그대로 '직전 고점'으로 쓴다 (눈대중 금지).
      const prior = Math.max(...P.breakout.slice(N - VIS, 110));
      return {
        price: P.breakout,
        hlines: [{ value: prior, color: "#dc2626", label: "직전 고점" }],
        markers: [{ i: firstAbove(P.breakout, prior, 105), tone: "bullish", label: "돌파" }],
        caption: "붉은 점선이 직전 고점 — 그 위로 봉이 올라선 지점이 돌파",
      };
    })(),
  },
  {
    key: "levels",
    name: "지지선 · 저항선",
    group: "가격대",
    what: "최근 차트에서 여러 번 되돌려진 저점을 지지선, 여러 번 막힌 고점을 저항선으로 잡습니다. 이 사이트는 최근 120거래일의 봉우리·골짜기와 최근 20거래일의 고가·저가를 후보로 놓고, 그중 현재가에 가장 가까운 값을 씁니다.",
    read: [
      { tone: "bullish", text: "지지선 근처까지 내려오면 여기서 버티는지가 관건인 자리." },
      { tone: "bearish", text: "저항선 바로 아래면 뚫는지 막히는지가 관건인 자리." },
    ],
    caveat: "지지선은 뚫리는 순간 저항선으로 바뀝니다. '지지선이니까 안전하다'는 뜻이 결코 아닙니다.",
    chart: {
      price: P.box,
      hlines: [
        { value: Math.max(...shown(P.box)), color: "#dc2626", label: "저항" },
        { value: Math.min(...shown(P.box)), color: "#16a34a", label: "지지" },
      ],
      caption: "위아래 점선 사이를 오가는 박스권 — 위에서 막히면 저항, 아래에서 받쳐지면 지지",
    },
  },
];

// ---------------------------------------------------------------- 행동 신호
export interface ActionDoc {
  key: string;
  emoji: string;
  label: string;
  when: string;
  watch: string;
}

export const ACTION_DOCS: ActionDoc[] = [
  {
    key: "chase", emoji: "🚀", label: "추격 매수 신호",
    when: "상승 추세에서 60일 신고가·저항선을 뚫었고, 거래량이 붙었거나 60일선이 뚜렷이 서 있을 때.",
    watch: "돌파가 실패해 되밀리면 손실도 빠릅니다. 돌파한 가격대를 다시 내주는지 확인하세요.",
  },
  {
    key: "addBuy", emoji: "➕", label: "추가 매수(눌림목) 신호",
    when: "정배열 상승 추세인데 주가가 20일선 ±3% 안으로 쉬어 가고, RSI가 35~62의 중립권일 때.",
    watch: "20일선을 확실히 깨고 내려가면 눌림목이 아니라 추세 이탈입니다.",
  },
  {
    key: "buy", emoji: "📈", label: "매수 전환 신호",
    when: "골든크로스가 났거나, 종합 점수가 +25 이상이면서 60일선이 위를 향할 때.",
    watch: "추세 전환 초입은 되돌림이 잦습니다. 신호 하나만으로 판단하지 마세요.",
  },
  {
    key: "takeProfit", emoji: "💰", label: "과열 — 분할 차익실현 구간",
    when: "RSI 70 이상이거나 볼린저밴드 위쪽 선을 뚫었는데, 종합 점수는 아직 양수일 때.",
    watch: "과열이 곧 하락은 아닙니다. 강세장에서는 과열 상태로 더 오르기도 합니다.",
  },
  {
    key: "reduce", emoji: "📉", label: "비중 축소 신호",
    when: "데드크로스가 났거나 종합 점수가 -25 이하일 때.",
    watch: "이미 많이 빠진 뒤에 나오는 후행 신호일 수 있습니다.",
  },
  {
    key: "stopLoss", emoji: "🛑", label: "지지선 이탈 — 손절 유의",
    when: "60일 신저가를 밑돌면서 60일선도 아래를 향할 때, 또는 하락 추세에서 지지선까지 내준 경우.",
    watch: "가장 먼저 판정합니다. 다른 지표가 좋아도 이 신호가 뜨면 그쪽을 먼저 보라는 뜻입니다.",
  },
  {
    key: "rebound", emoji: "🔍", label: "낙폭 과대 — 반등 확인 구간",
    when: "하락 추세에서 RSI가 30 이하로 내려갔을 때.",
    watch: "하락 추세 자체가 꺾였다는 뜻은 아닙니다. 바닥은 지나고 나서야 알 수 있습니다.",
  },
  {
    key: "hold", emoji: "👀", label: "관망 구간",
    when: "위 어디에도 해당하지 않을 때. 지표가 서로 엇갈리는 상태입니다.",
    watch: "신호가 없다는 것도 정보입니다. 억지로 방향을 찾을 필요는 없습니다.",
  },
];

export const SCORE_BANDS: { range: string; label: string; tone: "bullish" | "bearish" | "neutral" }[] = [
  { range: "+45 ~ +100", label: "강한 매수 신호", tone: "bullish" },
  { range: "+15 ~ +44", label: "매수 우위", tone: "bullish" },
  { range: "-14 ~ +14", label: "중립 · 관망", tone: "neutral" },
  { range: "-44 ~ -15", label: "매도 우위", tone: "bearish" },
  { range: "-100 ~ -45", label: "강한 매도 신호", tone: "bearish" },
];
