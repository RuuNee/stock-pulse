/**
 * `src/lib/indicators.ts` 가 파이프라인과 같은 값을 내는지 검사한다.
 *
 * 지표 계산을 브라우저로 옮기면서 같은 수식이 두 곳에 생겼다. 종목 JSON 에는
 * 더 이상 `indicators` 가 없어서 실데이터로 대조할 수 없으므로, 파이썬이 만든
 * 고정 픽스처(`tests/fixtures/indicators_parity.json`)를 양쪽에서 검사한다.
 * 파이썬 쪽은 `tests/test_indicators_parity.py`.
 *
 * 실행: npm run check-indicators
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const FIXTURE = path.join(ROOT, "tests", "fixtures", "indicators_parity.json");

/** 타입 주석만 걷어내고 TS 모듈을 그대로 실행한다 (빌드 의존성을 안 만든다). */
async function loadIndicators() {
  const src = fs
    .readFileSync(path.join(HERE, "..", "src", "lib", "indicators.ts"), "utf8")
    .replace(/export type [^\n]+\n/g, "")
    .replace(/: Series/g, "")
    .replace(/: Indicators/g, "")
    .replace(/: \(string \| number\)\[\]\[\]/g, "")
    .replace(/: number \| null/g, "")
    .replace(/: number\[\]/g, "")
    .replace(/: number(?= *[,)=])/g, "")
    .replace(/new Array<number>/g, "new Array")
    .replace(/export /g, "");
  const b64 = Buffer.from(`${src}\nexport { computeIndicators };`).toString("base64");
  return import(`data:text/javascript;base64,${b64}`);
}

const { computeIndicators } = await loadIndicators();
const fixture = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
const got = computeIndicators(fixture.rows);

// 파이썬 round() 는 은행가 반올림, JS Math.round() 는 올림이라 정확히 .5 인
// 값에서 마지막 자리가 갈릴 수 있다. 표시상 무의미하므로 그만큼만 허용한다.
const TOL = 0.011;
const problems = [];

for (const [key, expected] of Object.entries(fixture.expected)) {
  const actual = got[key];
  if (!actual) {
    problems.push(`${key}: TS 구현에 없는 시계열`);
    continue;
  }
  if (actual.length !== expected.length) {
    problems.push(`${key}: 길이 ${actual.length} vs ${expected.length}`);
    continue;
  }
  for (let i = 0; i < expected.length; i++) {
    const a = actual[i];
    const b = expected[i];
    if (a == null && b == null) continue;
    if (a == null || b == null) {
      problems.push(`${key}[${i}]: null 여부가 다름 (${a} vs ${b})`);
    } else if (Math.abs(a - b) > TOL) {
      problems.push(`${key}[${i}]: ${a} vs ${b}`);
    }
    if (problems.length > 10) break;
  }
  if (problems.length > 10) break;
}

const extra = Object.keys(got).filter((k) => !(k in fixture.expected));
if (extra.length) problems.push(`픽스처에 없는 시계열: ${extra.join(", ")}`);

if (problems.length) {
  console.error("지표 구현이 파이프라인과 어긋납니다:");
  for (const p of problems.slice(0, 10)) console.error(`  - ${p}`);
  console.error(
    "\n수식을 고쳤다면 pipeline/analyze/technical.py · web/src/lib/indicators.ts ·" +
      " tests/fixtures/indicators_parity.json 을 같은 커밋에서 맞추세요.",
  );
  process.exit(1);
}

const points = Object.values(fixture.expected).reduce((n, s) => n + s.length, 0);
console.log(`지표 일치 확인 — ${Object.keys(fixture.expected).length}개 시계열 · ${points}점`);
