import type { Mood } from "../lib/types";

const BG: Record<string, string> = {
  green: "linear-gradient(135deg,#16a34a22,#16a34a08)",
  amber: "linear-gradient(135deg,#f59e0b22,#f59e0b08)",
  red: "linear-gradient(135deg,#e11d4822,#e11d4808)",
};
const DOT: Record<string, string> = { green: "🟢", amber: "🟡", red: "🔴" };
const RING: Record<string, string> = { green: "#16a34a", amber: "#f59e0b", red: "#e11d48" };

export default function MoodCard({ title, mood }: { title: string; mood: Mood }) {
  return (
    <div className="card p-4" style={{ background: BG[mood.color] }}>
      <div className="flex items-center gap-3">
        <Gauge score={mood.score} color={RING[mood.color]} />
        <div className="min-w-0">
          <div className="text-sm" style={{ color: "var(--muted)" }}>
            {title} 시장 분위기
          </div>
          <div className="text-xl font-bold">
            {DOT[mood.color]} {mood.label}{" "}
            <span className="text-base font-normal" style={{ color: "var(--muted)" }}>
              {mood.score}점
            </span>
          </div>
        </div>
      </div>
      {mood.reason && <p className="mt-2.5 text-sm leading-relaxed">{mood.reason}</p>}
    </div>
  );
}

function Gauge({ score, color }: { score: number; color: string }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  const off = c * (1 - score / 100);
  return (
    <svg width={56} height={56} viewBox="0 0 56 56" className="shrink-0">
      <circle cx="28" cy="28" r={r} fill="none" stroke="var(--border)" strokeWidth="5" />
      <circle
        cx="28"
        cy="28"
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="5"
        strokeDasharray={c}
        strokeDashoffset={off}
        strokeLinecap="round"
        transform="rotate(-90 28 28)"
      />
      <text x="28" y="33" textAnchor="middle" fontSize="15" fontWeight="700" fill="var(--text)">
        {score}
      </text>
    </svg>
  );
}
