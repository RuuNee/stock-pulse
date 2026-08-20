/**
 * 차트 지표를 브라우저에서 계산한다.
 *
 * 예전에는 파이프라인이 계산해서 종목 JSON 에 `indicators` 로 실어 보냈다.
 * 그런데 이 11개 시계열이 종목 파일의 절반 가까이를 차지했다 — 확대분 44KB 중
 * 21.4KB, 코어는 91KB 중 42KB. 종목이 895개고 sync 마다 전부 다시 커밋되니
 * 그대로 `.git` 증식이 된다. 전부 OHLCV 에서 파생되는 값이라 안 보내도 된다.
 *
 * **수식은 `pipeline/analyze/technical.py` 의 `series()` 와 1:1 로 맞춰야 한다.**
 * 차트에 그려진 선과 분석 카드가 말하는 근거(`analysis`, 여전히 서버 계산)가
 * 어긋나면 안 되기 때문이다. 바꿀 일이 생기면 양쪽을 같이 고칠 것.
 * `tests/test_indicators_parity.py` 가 두 구현의 일치를 고정한다.
 */

export type Series = (number | null)[];
export type Indicators = Record<string, Series>;

/** pandas `round()` 와 같은 자리 맞춤. null 은 그대로 통과시킨다. */
function round(value: number | null, digits: number): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}

/** `close.rolling(period).mean()` — 창이 안 차면 null. */
function sma(values: number[], period: number, digits = 2): Series {
  const out: Series = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = round(sum / period, digits);
  }
  return out;
}

/** `close.ewm(span=..., adjust=False).mean()` — 첫 값에서 시작하는 재귀식. */
function ewmSpan(values: number[], span: number): number[] {
  const alpha = 2 / (span + 1);
  return ewmAlpha(values, alpha);
}

function ewmAlpha(values: number[], alpha: number): number[] {
  const out = new Array<number>(values.length);
  let prev = values[0] ?? 0;
  out[0] = prev;
  for (let i = 1; i < values.length; i++) {
    prev = alpha * values[i] + (1 - alpha) * prev;
    out[i] = prev;
  }
  return out;
}

/**
 * `close.rolling(period).std()` — pandas 기본값 ddof=1 (표본 표준편차)이다.
 * 모표준편차(ddof=0)를 쓰면 볼린저밴드 폭이 좁아져서 서버 판정과 어긋난다.
 */
function rollingStd(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    const mean = sum / period;
    let sq = 0;
    for (let j = i - period + 1; j <= i; j++) sq += (values[j] - mean) ** 2;
    out[i] = Math.sqrt(sq / (period - 1));
  }
  return out;
}

/**
 * Wilder RSI. 파이썬 쪽은 `ewm(alpha=1/period, adjust=False)` 를 쓰고,
 * loss 가 0 인 구간(하락이 한 번도 없던 초반)은 NaN → 50 으로 메운다.
 */
export function rsi(values: number[], period = 14): Series {
  if (values.length === 0) return [];
  const gains = new Array<number>(values.length).fill(0);
  const losses = new Array<number>(values.length).fill(0);
  for (let i = 1; i < values.length; i++) {
    const delta = values[i] - values[i - 1];
    gains[i] = delta > 0 ? delta : 0;
    losses[i] = delta < 0 ? -delta : 0;
  }
  // `close.diff()` 의 첫 값은 NaN 이고 clip 뒤에도 NaN 이다. pandas 의
  // `ewm(adjust=False)` 는 선행 NaN 을 건너뛰고 **첫 유효값을 시드로** 잡는다.
  // 0 을 시드로 쓰면 alpha=1/14 기준 100봉 넘게 값이 어긋난다 (실측 최대 45).
  const alpha = 1 / period;
  const avgGain = ewmAlpha(gains.slice(1), alpha);
  const avgLoss = ewmAlpha(losses.slice(1), alpha);

  return values.map((_, i) => {
    if (i === 0) return 50; // diff 가 NaN → rs 도 NaN → fillna(50)
    const g = avgGain[i - 1];
    const l = avgLoss[i - 1];
    if (l === 0) return 50; // loss 가 0 이면 NaN → fillna(50)
    return round(100 - 100 / (1 + g / l), 1);
  });
}

export function macd(values: number[], fast = 12, slow = 26, signal = 9) {
  const fastE = ewmSpan(values, fast);
  const slowE = ewmSpan(values, slow);
  const line = values.map((_, i) => fastE[i] - slowE[i]);
  const sig = ewmSpan(line, signal);
  const hist = line.map((v, i) => v - sig[i]);
  return { line, signal: sig, hist };
}

export function bollinger(values: number[], period = 20, mult = 2) {
  const mid = sma(values, period);
  const sd = rollingStd(values, period);
  const upper: Series = [];
  const lower: Series = [];
  for (let i = 0; i < values.length; i++) {
    const m = mid[i];
    const s = sd[i];
    if (m == null || s == null) {
      upper.push(null);
      lower.push(null);
    } else {
      upper.push(round(m + mult * s, 2));
      lower.push(round(m - mult * s, 2));
    }
  }
  return { mid, upper, lower };
}

/**
 * `pipeline/analyze/technical.py::series()` 와 같은 키·같은 자릿수로 낸다.
 * `volMa20` 은 차트가 쓰지 않아서 뺐다 (서버 판정은 자체 계산을 쓴다).
 */
export function computeIndicators(rows: (string | number)[][]): Indicators {
  const close = rows.map((r) => Number(r[4]));
  const { upper, lower } = bollinger(close);
  const m = macd(close);

  return {
    ma5: sma(close, 5),
    ma20: sma(close, 20),
    ma60: sma(close, 60),
    ma120: sma(close, 120),
    rsi14: rsi(close, 14),
    bbUpper: upper,
    bbLower: lower,
    // MACD 는 원화 종목이면 수백, 미국 저가주면 0.0x 라 자릿수를 넉넉히 둔다.
    macd: m.line.map((v) => round(v, 3)),
    macdSignal: m.signal.map((v) => round(v, 3)),
    macdHist: m.hist.map((v) => round(v, 3)),
  };
}
