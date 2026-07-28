import { useState } from "react";

// 갱신 주기. "뉴스도 차트도 실시간이겠지" 라는 오해가 실제로 나왔다 — 셋 다 주기가
// 다르고 실시간인 건 하나도 없다. 워크플로를 바꾸면 여기도 같이 고쳐야 한다:
//   pulse      .github/workflows/pulse.yml       cron "0 */2 * * *"
//   data-sync  .github/workflows/data-sync.yml   cron "30 7,21 * * 1-5"
//   brief      .github/workflows/brief-*.yml     개장 전 발송 창 (pipeline/config.py)
// 뉴스와 지수는 같은 잡(pulse)이라 한 줄로 묶었다.
const ROWS: Array<[string, string]> = [
  ["뉴스 · 지수 · 환율 · 유가", "2시간마다 (주말 포함)"],
  ["종목 가격 · 차트", "평일 하루 2번, 각 장 마감 직후"],
  ["장전 브리핑", "거래일 하루 1번, 개장 20~75분 전"],
];

/** 탭/호버하면 갱신 주기를 펼쳐 보여 주는 작은 힌트. `Term` 과 같은 관용구를 쓴다. */
export default function UpdateTip({ label = "🕒 갱신 주기", up }: { label?: string; up?: boolean }) {
  const [open, setOpen] = useState(false);

  return (
    <span className="relative inline-block">
      <span
        className="term"
        tabIndex={0}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onBlur={() => setOpen(false)}
      >
        {label}
      </span>
      {open && (
        <span
          // 트리거 기준 가운데 정렬 — 홈 하단(가운데)과 종목 페이지(왼쪽) 양쪽에서 안 잘린다.
          className={`absolute z-30 left-1/2 -translate-x-1/2 w-72 max-w-[85vw] p-3 rounded-xl text-sm shadow-lg block text-left ${
            up ? "bottom-full mb-1" : "top-full mt-1"
          }`}
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--text)" }}
          onClick={(e) => e.stopPropagation()}
        >
          <b className="block mb-2">얼마나 자주 갱신되나요?</b>
          {/* 값을 라벨 아래에 쌓는다 — 2단으로 두면 좁은 폭에서 "각 장 / 마감 직후" 처럼 잘린다. */}
          <span className="flex flex-col gap-2">
            {ROWS.map(([what, when]) => (
              <span key={what} className="block">
                <span className="block font-medium">{what}</span>
                <span className="block" style={{ color: "var(--muted)" }}>
                  {when}
                </span>
              </span>
            ))}
          </span>
          <span className="block mt-2 pt-2 text-xs" style={{ color: "var(--muted)", borderTop: "1px solid var(--border)" }}>
            차트는 하루에 봉 하나가 그려지는 <b>일봉</b>이에요. 장중 실시간 시세는 제공하지 않습니다.
          </span>
        </span>
      )}
    </span>
  );
}
