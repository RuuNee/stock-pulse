import type { IndicatorStyle } from "../lib/signals";

/** 지표 색 견본 — 실선/점선까지 차트와 똑같이 그린 짧은 선 한 토막.
 *
 *  "주황 5일선"처럼 색 이름을 글로 적으면 초보가 화면의 어느 선인지 못 찾는다.
 *  (주황과 노랑, 보라와 남색은 말로 구분되지 않는다.) 실제로 그려서 보여준다. */
export function LineSwatch({ color, dash }: { color: string; dash?: boolean }) {
  return (
    <svg width="20" height="8" aria-hidden style={{ flexShrink: 0 }}>
      <line
        x1="1" y1="4" x2="19" y2="4"
        stroke={color} strokeWidth="2.4" strokeLinecap="round"
        strokeDasharray={dash ? "4 3" : undefined}
      />
    </svg>
  );
}

/** 견본 + 이름 한 쌍. */
export function LegendItem({ color, label, dash }: IndicatorStyle) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <LineSwatch color={color} dash={dash} />
      <span>{label}</span>
    </span>
  );
}

/** 여러 개를 줄바꿈 가능한 한 줄로.
 *
 *  `title` 로 패널을 밝힌다. RSI·%K 는 20일선과 같은 보라를 쓰는데(둘 다 별도
 *  패널에 그려지니 차트에서는 안 겹친다), 범례를 한 줄로 늘어놓으면 같은 색이
 *  나란히 서서 서로 관련 있는 선처럼 보인다. 어느 패널의 선인지 앞에 적어 준다. */
export default function Legend({
  items,
  title,
  className = "",
}: {
  items: IndicatorStyle[];
  title?: string;
  className?: string;
}) {
  if (!items.length) return null;
  return (
    <div
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] ${className}`}
      style={{ color: "var(--muted)" }}
    >
      {title && <span className="font-semibold opacity-80">{title}</span>}
      {items.map((it) => <LegendItem key={it.label} {...it} />)}
    </div>
  );
}
