import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import NewsCard from "../components/NewsCard";
import type { NewsItem } from "../lib/types";

type Filter = "전체" | "국장" | "미장" | "정책" | "실적" | "산업" | "종목";

const FILTERS: Filter[] = ["전체", "국장", "미장", "정책", "실적", "산업", "종목"];

export default function News() {
  const { data, loading, error } = useAsync(() => api.news());
  const [filter, setFilter] = useState<Filter>("전체");
  const [limit, setLimit] = useState(40);

  const filtered = useMemo(() => {
    const items = data ?? [];
    return items.filter((n) => matches(n, filter));
  }, [data, filter]);

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">뉴스</h1>

      <div className="scroll-x -mx-1 px-1">
        <div className="flex gap-1.5 pb-1">
          {FILTERS.map((f) => (
            <button key={f} className={`chip ${filter === f ? "active" : ""}`} onClick={() => { setFilter(f); setLimit(40); }}>
              {f}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <div className="card p-8 text-center text-sm" style={{ color: "var(--muted)" }}>뉴스를 불러오지 못했습니다.</div>
      ) : (
        <div className="flex flex-col gap-2.5">
          {loading
            ? Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton" style={{ height: 84 }} />)
            : filtered.slice(0, limit).map((n) => <NewsCard key={n.id} item={n} />)}
          {!loading && filtered.length === 0 && (
            <div className="card p-8 text-center text-sm" style={{ color: "var(--muted)" }}>해당하는 뉴스가 없습니다.</div>
          )}
          {!loading && filtered.length > limit && (
            <button className="card p-3 text-center text-sm font-medium" onClick={() => setLimit((l) => l + 40)}>
              더 보기 ({filtered.length - limit}건)
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function matches(n: NewsItem, f: Filter): boolean {
  switch (f) {
    case "전체":
      return true;
    case "국장":
      return n.market === "KR";
    case "미장":
      return n.market === "US" || n.market === "GLOBAL";
    default:
      return n.category === f;
  }
}
