// Turn raw numbers into beginner-friendly Korean strings (UIUX §3-3).

export function fmtPrice(value: number | null, currency = "KRW"): string {
  if (value == null) return "-";
  if (currency === "USD") {
    return "$" + value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return Math.round(value).toLocaleString("ko-KR") + "원";
}

export function fmtPct(pct: number | null): string {
  if (pct == null) return "-";
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

// 1554000000000000 -> "1,554조원" (KR) / "$1.55T" (US)
export function fmtMarcap(value: number | null, currency = "KRW"): string {
  if (value == null) return "-";
  if (currency === "USD") {
    if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
    if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
    return `$${(value / 1e6).toFixed(0)}M`;
  }
  const jo = value / 1e12;
  if (jo >= 1) return `${Math.round(jo).toLocaleString("ko-KR")}조원`;
  return `${Math.round(value / 1e8).toLocaleString("ko-KR")}억원`;
}

export function fmtVolume(value: number): string {
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}억주`;
  if (value >= 1e4) return `${Math.round(value / 1e4).toLocaleString("ko-KR")}만주`;
  return value.toLocaleString("ko-KR") + "주";
}

// Plain-language magnitude label for a move (beginner mode).
export function moveLabel(pct: number | null): string {
  if (pct == null) return "";
  const a = Math.abs(pct);
  const dir = pct >= 0 ? "올랐어요" : "내렸어요";
  if (a >= 8) return `많이 ${dir}`;
  if (a >= 3) return `꽤 ${dir}`;
  if (a >= 1) return `조금 ${dir}`;
  return `거의 그대로예요`;
}

export function volLabel(ratio: number | null): string {
  if (ratio == null) return "";
  return `평소의 ${ratio.toFixed(1)}배`;
}

// "3시간 전" style relative time.
export function timeAgo(iso?: string): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "방금 전";
  if (min < 60) return `${min}분 전`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}일 전`;
  return new Date(iso).toLocaleDateString("ko-KR");
}

export function fmtDateKr(iso: string): string {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  const w = ["일", "월", "화", "수", "목", "금", "토"][d.getDay()];
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 (${w})`;
}
