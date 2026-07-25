import { Link } from "react-router-dom";
import type { NewsItem } from "../lib/types";
import { timeAgo } from "../lib/format";

const CAT_COLOR: Record<string, string> = {
  정책: "#f59e0b",
  실적: "#10b981",
  산업: "#6366f1",
  국제: "#ec4899",
  종목: "#06b6d4",
  시장: "#94a3b8",
  암호화폐: "#f97316",
};

// Root is a <div> (not <a>) so the ticker chips below can be real <Link>s
// without nesting anchors. The headline block is the article link.
export default function NewsCard({ item, why }: { item: NewsItem; why?: string }) {
  const important = (item.importance ?? 0) >= 75;
  return (
    <div className="card p-3.5" style={important ? { borderColor: "var(--up)" } : undefined}>
      <a href={item.url} target="_blank" rel="noopener noreferrer" className="block transition hover:brightness-110">
        <div className="flex items-center gap-2 mb-1.5 text-xs" style={{ color: "var(--muted)" }}>
          {item.category && (
            <span
              className="px-1.5 py-0.5 rounded"
              style={{ background: (CAT_COLOR[item.category] ?? "#94a3b8") + "22", color: CAT_COLOR[item.category] ?? "#94a3b8" }}
            >
              {item.category}
            </span>
          )}
          <span>{item.source}</span>
          <span>·</span>
          <span>{timeAgo(item.publishedAt)}</span>
          {important && <span style={{ color: "var(--up)" }}>★ 중요</span>}
        </div>

        <div className="font-semibold leading-snug">
          {item.titleKo || item.title}
          {item.titleKo && (
            <span className="ml-1.5 text-[10px] align-middle" style={{ color: "var(--muted)" }} title={item.title}>
              🌐 번역
            </span>
          )}
        </div>
        {(item.summaryKo || item.summary) && (
          <div className="mt-1 text-sm line-clamp-2" style={{ color: "var(--muted)" }}>
            {item.summaryKo || item.summary}
          </div>
        )}
      </a>

      {why && (
        <div className="mt-2 text-sm rounded-lg px-2.5 py-1.5" style={{ background: "var(--surface-2)" }}>
          💡 {why}
        </div>
      )}

      {item.tickers.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.tickers.slice(0, 4).map((t) => (
            <Link key={t.code} to={`/ticker/${t.market}/${t.code}`} className="chip" style={{ padding: "3px 9px", fontSize: 12 }}>
              {t.name}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
