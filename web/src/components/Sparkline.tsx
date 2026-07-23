import { useSettings } from "../lib/settings";

// Tiny inline SVG trend line. Colored by first->last direction.
export default function Sparkline({
  data,
  width = 96,
  height = 32,
}: {
  data: number[];
  width?: number;
  height?: number;
}) {
  const s = useSettings();
  if (!data || data.length < 2) return <svg width={width} height={height} />;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const step = width / (data.length - 1);
  const points = data
    .map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / span) * height).toFixed(1)}`)
    .join(" ");
  const up = data[data.length - 1] >= data[0];
  const color = up ? s.upColor : s.downColor;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <polyline points={points} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}
