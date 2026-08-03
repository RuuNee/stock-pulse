import { useSettings } from "../lib/settings";
import { ACTION_TONE, verdictColor } from "../lib/signals";
import type { AnalysisBrief } from "../lib/types";

/** 목록·브리핑에서 쓰는 한 줄짜리 신호 칩. 이모지 + 행동 문구 + 점수. */
export default function SignalBadge({
  a,
  size = "md",
  showScore = true,
}: {
  a: AnalysisBrief;
  size?: "sm" | "md";
  showScore?: boolean;
}) {
  const s = useSettings();
  const color = verdictColor(ACTION_TONE[a.action] ?? "neutral", s);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border whitespace-nowrap"
      style={{
        borderColor: color,
        color,
        padding: size === "sm" ? "1px 8px" : "3px 10px",
        fontSize: size === "sm" ? 11 : 12.5,
        fontWeight: 600,
      }}
      title={a.headline}
    >
      <span aria-hidden>{a.actionEmoji}</span>
      <span>{a.actionLabel}</span>
      {showScore && (
        <span className="tabular-nums" style={{ opacity: 0.8 }}>
          {a.score > 0 ? `+${a.score}` : a.score}점
        </span>
      )}
    </span>
  );
}
