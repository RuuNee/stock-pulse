import { useSettings } from "../lib/settings";
import { fmtPct } from "../lib/format";

// Color + arrow (never color alone — 색맹 대비, UIUX §4).
export default function ChangeBadge({
  pct,
  size = "md",
}: {
  pct: number | null | undefined;
  size?: "sm" | "md" | "lg";
}) {
  const s = useSettings();
  const color = s.colorFor(pct);
  const arrow = pct == null ? "" : pct >= 0 ? "▲" : "▼";
  const cls = size === "lg" ? "text-lg font-bold" : size === "sm" ? "text-xs" : "text-sm font-semibold";
  return (
    <span className="inline-flex items-center gap-1" style={{ color }}>
      <span className={cls}>
        {arrow} {fmtPct(pct ?? null)}
      </span>
    </span>
  );
}
