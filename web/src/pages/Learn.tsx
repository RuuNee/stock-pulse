import { useSearchParams } from "react-router-dom";
import { TERMS } from "../lib/terms";
import { ACTION_DOCS, CHART_GUIDE, SCORE_BANDS, VIS, type GuideItem } from "../lib/chartGuide";
import PatternChart, { CandleAnatomy } from "../components/PatternChart";
import { LineSwatch } from "../components/LineSwatch";
import { useSettings } from "../lib/settings";
import { GROUP_ICON, INDICATOR, verdictColor, VERDICT_MARK } from "../lib/signals";

const GROUPS: { title: string; keys: string[] }[] = [
  { title: "기본 용어", keys: ["marcap", "volume", "amount", "per", "pbr", "roe", "eps", "dividend", "etf"] },
  { title: "차트 보는 법", keys: ["ma", "goldencross", "deadcross", "rsi", "macd", "bollinger", "stochastic", "disparity", "support", "resistance", "breakout", "gap", "zscore", "atr"] },
  { title: "시장 구조", keys: ["kospi", "kosdaq", "sp500", "nasdaq", "dow", "circuit", "short"] },
  { title: "거시 경제", keys: ["fx", "rate", "ytnx", "inflation", "fomc", "vix", "foreign", "institution"] },
  { title: "실적·이벤트", keys: ["earning", "guidance"] },
];

const TABS = [
  { id: "terms", label: "📖 용어사전" },
  { id: "chart", label: "📊 차트분석" },
] as const;

// 색 약속 표. "며칠 평균인지"가 아니라 "그래서 뭘 보는 선인지"를 오른쪽에 적는다.
const COLOR_KEYS = [
  "ma5", "ma20", "ma60", "ma120", "bb", "macd", "macdSignal", "rsi",
] as const;

const COLOR_NOTE: Record<(typeof COLOR_KEYS)[number], string> = {
  ma5: "최근 1주일 분위기",
  ma20: "최근 한 달 — 눌림목 기준선",
  ma60: "최근 3개월 — 중기 추세",
  ma120: "최근 반년 — 장기 바닥선",
  bb: "주가가 움직이는 통로",
  macd: "추세 전환을 보는 선",
  macdSignal: "MACD와 비교하는 선",
  rsi: "과열·침체 (0~100)",
};

export default function Learn() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "chart" ? "chart" : "terms";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold">도움말</h1>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          모르는 단어와 차트 기법을 쉬운 말로 풀어 설명합니다.
        </p>
      </div>

      <div className="flex gap-1.5">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`chip ${tab === t.id ? "active" : ""}`}
            onClick={() => setParams(t.id === "terms" ? {} : { tab: t.id }, { replace: true })}
            aria-pressed={tab === t.id}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "terms" ? <TermsTab /> : <ChartTab />}
    </div>
  );
}

// ------------------------------------------------------------------ 용어사전
function TermsTab() {
  return (
    <>
      {GROUPS.map((g) => (
        <section key={g.title}>
          <h2 className="text-base font-bold mb-2.5">{g.title}</h2>
          <div className="grid sm:grid-cols-2 gap-2.5">
            {g.keys.map((k) => {
              const e = TERMS[k];
              if (!e) return null;
              return (
                <div key={k} className="card p-3.5">
                  <div className="font-semibold text-sm">{e.title}</div>
                  <p className="mt-1 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>{e.short}</p>
                  {e.more && <p className="mt-1 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>{e.more}</p>}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </>
  );
}

// ------------------------------------------------------------------ 차트분석
function ChartTab() {
  const s = useSettings();
  return (
    <>
      <section className="card p-4">
        <h2 className="text-base font-bold">이 페이지를 보는 순서</h2>
        <ol className="mt-2 flex flex-col gap-1.5 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
          <li><b style={{ color: "var(--text)" }}>1.</b> 봉(캔들) 하나가 무슨 뜻인지 — 아래 그림 한 장이면 끝납니다.</li>
          <li><b style={{ color: "var(--text)" }}>2.</b> 종목 화면의 <b style={{ color: "var(--text)" }}>기법별 판정</b>에 나오는 11가지가 각각 무엇을 재는지.</li>
          <li><b style={{ color: "var(--text)" }}>3.</b> 그 11가지가 어떻게 합쳐져 <b style={{ color: "var(--text)" }}>하나의 신호</b>가 되는지.</li>
          <li><b style={{ color: "var(--text)" }}>4.</b> 이 분석이 <b style={{ color: "var(--text)" }}>언제 틀리는지</b> — 이게 제일 중요합니다.</li>
        </ol>
      </section>

      {/* 0. 캔들 */}
      <section>
        <h2 className="text-base font-bold mb-2.5">봉(캔들) 읽는 법</h2>
        <div className="card p-4 flex flex-col gap-3">
          <CandleAnatomy />
          <p className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
            봉 하나가 하루입니다. 몸통의 <b style={{ color: "var(--text)" }}>위아래 끝</b>이 그날의 시작가와
            마지막 가격이고, 위아래로 삐져나온 <b style={{ color: "var(--text)" }}>가는 선</b>이 하루 중 가장
            비쌌던 값과 싼 값입니다. 몸통이 길수록 그날 방향이 뚜렷했다는 뜻이고, 위아래 선만
            길다면 많이 흔들렸지만 결국 제자리로 돌아왔다는 뜻입니다.
          </p>
          <p className="text-xs" style={{ color: "var(--muted)" }}>
            색은 한국식(오르면 빨강)과 미국식(오르면 초록) 중에 고를 수 있습니다 —
            왼쪽 메뉴 아래 <b>{s.colorMode === "kr" ? "🔴 상승 / 🔵 하락" : "🟢 상승 / 🔴 하락"}</b> 버튼.
            초보 모드에서는 봉 대신 종가를 이은 선 하나로 단순하게 보여 줍니다.
          </p>
        </div>
      </section>

      {/* 색 약속 — 아래 예시와 종목 차트가 쓰는 색이 같다는 걸 먼저 못박는다 */}
      <section>
        <h2 className="text-base font-bold mb-1">지표 색 약속</h2>
        <p className="text-sm mb-2.5" style={{ color: "var(--muted)" }}>
          아래 예시 차트와 <b>종목 화면의 실제 차트가 같은 색</b>을 씁니다.
          종목 화면에서 <b>이동평균 · 볼린저 · MACD · RSI</b> 칩을 켜면 여기 색 그대로 그려집니다.
        </p>
        <div className="card p-4 grid sm:grid-cols-2 gap-x-6 gap-y-2.5">
          {COLOR_KEYS.map((k) => {
            const it = INDICATOR[k];
            return (
              <div key={k} className="flex items-center gap-2.5 text-sm">
                <LineSwatch color={it.color} dash={"dash" in it ? it.dash : undefined} />
                <span className="font-medium">{it.label}</span>
                <span className="ml-auto text-xs text-right" style={{ color: "var(--muted)" }}>
                  {COLOR_NOTE[k]}
                </span>
              </div>
            );
          })}
        </div>
        <p className="mt-2 text-xs" style={{ color: "var(--muted)" }}>
          점선(┄)은 보조선이라는 뜻입니다 — 볼린저 통로의 위아래 선, MACD의 시그널선, 스토캐스틱의 %D.
        </p>
      </section>

      {/* 1. 기법 11가지 */}
      <section>
        <h2 className="text-base font-bold mb-1">기법 11가지</h2>
        <p className="text-sm mb-3" style={{ color: "var(--muted)" }}>
          종목 화면 <b>📊 차트 분석 → 기법별 판정</b>에 뜨는 항목과 같은 이름·같은 순서입니다.
          예시 그림은 실제 계산식으로 그린 것이라 종목 차트에서 지표를 켰을 때와 색이 같습니다.
        </p>
        <div className="flex flex-col gap-3">
          {CHART_GUIDE.map((g) => <GuideCard key={g.key} g={g} />)}
        </div>
      </section>

      {/* 2. 합산 방식 */}
      <section>
        <h2 className="text-base font-bold mb-2.5">신호가 만들어지는 방법</h2>
        <div className="card p-4 flex flex-col gap-3">
          <p className="text-sm leading-relaxed">
            기법 11가지를 각각 <b>강세 / 약세 / 중립</b>으로 판정하고, 중요도(가중치 1~3)와
            신호의 세기(0~1)를 곱해 더합니다. 그 값을 <b>-100 ~ +100</b>으로 환산한 것이 종합 점수입니다.
            중립 판정도 계산에 함께 들어가기 때문에, 11개 중 2~3개만 강세인 종목이 강한 신호로
            둔갑하지 않습니다.
          </p>
          <div className="flex flex-col gap-1.5">
            {SCORE_BANDS.map((b) => (
              <div key={b.range} className="flex items-center gap-3 text-sm">
                <span className="tabular-nums w-24 shrink-0" style={{ color: "var(--muted)" }}>{b.range}</span>
                <span className="font-semibold" style={{ color: verdictColor(b.tone, s) }}>
                  {VERDICT_MARK[b.tone]} {b.label}
                </span>
              </div>
            ))}
          </div>
          <p className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
            점수만으로는 같은 "매수 우위"라도 이미 크게 오른 자리인지 눌린 자리인지 구분되지
            않습니다. 그래서 점수 위에 아래 <b>행동 신호</b>를 따로 붙입니다.
          </p>
        </div>
      </section>

      {/* 3. 행동 신호 */}
      <section>
        <h2 className="text-base font-bold mb-2.5">행동 신호 8가지</h2>
        <div className="grid sm:grid-cols-2 gap-2.5">
          {ACTION_DOCS.map((a) => (
            <div key={a.key} className="card p-3.5">
              <div className="font-semibold text-sm">{a.emoji} {a.label}</div>
              <p className="mt-1.5 text-sm leading-relaxed">
                <b style={{ color: "var(--muted)" }}>언제 뜨나 · </b>{a.when}
              </p>
              <p className="mt-1 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
                <b>주의 · </b>{a.watch}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* 4. 한계 */}
      <section>
        <h2 className="text-base font-bold mb-2.5">꼭 알아둘 한계</h2>
        <div className="card p-4">
          <ul className="flex flex-col gap-2.5 text-sm leading-relaxed">
            <Limit title="전부 후행 지표입니다">
              이동평균·MACD·RSI는 모두 지나간 가격을 요약한 값입니다. 그래서 방향이 바뀐 뒤에야
              신호가 나옵니다. 앞을 맞히는 도구가 아니라, 지금 모양을 정리해 주는 도구입니다.
            </Limit>
            <Limit title="횡보장에서는 계속 어긋납니다">
              방향 없는 구간에서는 크로스 신호가 났다 사라졌다를 반복합니다. 이 사이트가 60일선
              기울기와 종합 점수를 함께 보는 이유입니다.
            </Limit>
            <Limit title="실적·공시 같은 재료는 보지 않습니다">
              차트 분석은 가격과 거래량만 씁니다. 실적 발표, 유상증자, 소송 같은 재료는 같은 종목
              화면의 <b>📅 급등락일 &amp; 그날의 뉴스</b>에서 확인하세요. 두 가지를 같이 봐야 합니다.
            </Limit>
            <Limit title="추천이 아닙니다">
              "추격 매수 신호"는 <b>차트가 교과서에서 그렇게 부르는 모양이 됐다</b>는 관찰이지,
              사라거나 팔라는 권유가 아닙니다. 이 사이트는 목표가를 제시하지 않으며, 어떤 결정도
              대신하지 않습니다.
            </Limit>
          </ul>
        </div>
      </section>
    </>
  );
}

function GuideCard({ g }: { g: GuideItem }) {
  const s = useSettings();
  return (
    <article className="card p-4 flex flex-col gap-3">
      <div className="flex items-baseline gap-2 flex-wrap">
        <h3 className="font-bold">{g.name}</h3>
        <span className="chip" style={{ padding: "1px 8px", fontSize: 11 }}>
          {GROUP_ICON[g.group] ?? "•"} {g.group}
        </span>
      </div>

      <p className="text-sm leading-relaxed">{g.what}</p>

      <div>
        {/* 지표는 긴 시리즈로 계산해 두고, 캔들이 읽힐 만큼만 잘라 그린다. */}
        <PatternChart visible={VIS} {...g.chart} />
        <p className="mt-1.5 text-xs leading-relaxed" style={{ color: "var(--muted)" }}>
          {g.chart.caption}
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        {g.read.map((r, i) => (
          <div key={i} className="flex gap-2 text-sm leading-relaxed">
            <span className="shrink-0 font-semibold" style={{ color: verdictColor(r.tone, s) }}>
              {VERDICT_MARK[r.tone]}
            </span>
            <span>{r.text}</span>
          </div>
        ))}
      </div>

      <p className="text-sm leading-relaxed rounded-xl p-2.5" style={{ background: "var(--surface-2)", color: "var(--muted)" }}>
        ⚠️ <b>언제 틀리나 · </b>{g.caveat}
      </p>
    </article>
  );
}

function Limit({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <li className="flex flex-col gap-0.5">
      <b>· {title}</b>
      <span style={{ color: "var(--muted)" }}>{children}</span>
    </li>
  );
}
