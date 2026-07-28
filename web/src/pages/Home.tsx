import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { fmtDateKr } from "../lib/format";
import MoodCard from "../components/MoodCard";
import NewsCard from "../components/NewsCard";
import Sparkline from "../components/Sparkline";
import ChangeBadge from "../components/ChangeBadge";
import Term from "../components/Term";
import UpdateTip from "../components/UpdateTip";
import type { MacroIndex, Market } from "../lib/types";

export default function Home() {
  const overview = useAsync(() => api.overview());
  const news = useAsync(() => api.news());
  const manifest = useAsync(() => api.manifest());

  if (overview.error) return <EmptyState updated={null} />;

  const ov = overview.data;
  const topNews = (news.data ?? []).slice(0, 6);
  const today = manifest.data?.markets?.KR?.briefDate;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="text-sm" style={{ color: "var(--muted)" }}>
          📅 {today ? fmtDateKr(today) : "오늘"}
        </div>
        <h1 className="text-2xl font-bold mt-0.5">오늘의 시장 한눈에</h1>
      </div>

      {/* mood traffic lights */}
      <div className="grid sm:grid-cols-2 gap-3">
        {ov ? (
          (["KR", "US"] as Market[]).map((m) =>
            ov.marketMood[m] ? <MoodCard key={m} title={m === "KR" ? "국내" : "미국"} mood={ov.marketMood[m]} /> : null,
          )
        ) : (
          <><Sk h={110} /><Sk h={110} /></>
        )}
      </div>

      {/* index cards */}
      <section>
        <SectionTitle>시장 지표</SectionTitle>
        <div className="scroll-x -mx-1 px-1">
          <div className="flex gap-2.5 pb-1" style={{ minWidth: "min-content" }}>
            {ov
              ? ov.indices.filter((i) => i.group === "index" || i.group === "fx").slice(0, 8).map((i) => (
                  <IndexCard key={i.key} idx={i} />
                ))
              : Array.from({ length: 5 }).map((_, i) => <Sk key={i} w={140} h={92} />)}
          </div>
        </div>
      </section>

      {/* top news */}
      <section>
        <SectionTitle right={<Link to="/news" className="text-sm" style={{ color: "var(--accent)" }}>전체 →</Link>}>
          오늘의 주요 뉴스
        </SectionTitle>
        <div className="flex flex-col gap-2.5">
          {news.data
            ? topNews.map((n) => <NewsCard key={n.id} item={n} />)
            : Array.from({ length: 4 }).map((_, i) => <Sk key={i} h={80} />)}
        </div>
      </section>

      {/* quick links to markets */}
      <div className="grid grid-cols-2 gap-3">
        <Link to="/market/KR" className="card p-4 text-center font-semibold">🇰🇷 국장 보기</Link>
        <Link to="/market/US" className="card p-4 text-center font-semibold">🇺🇸 미장 보기</Link>
      </div>

      <p className="text-xs text-center leading-relaxed" style={{ color: "var(--muted)" }}>
        본 사이트는 공개된 뉴스를 정리한 <Term k="etf">정보 제공</Term> 서비스이며 투자 권유가 아닙니다.
        {manifest.data && (
          <>
            <br />마지막 갱신 {manifest.data.generatedAtKst} · <UpdateTip up />
          </>
        )}
      </p>
    </div>
  );
}

function IndexCard({ idx }: { idx: MacroIndex }) {
  return (
    <div className="card p-3 shrink-0" style={{ width: 150 }}>
      <div className="text-xs truncate" style={{ color: "var(--muted)" }}>{idx.name}</div>
      <div className="text-lg font-bold mt-0.5 tabular-nums">
        {idx.value != null ? idx.value.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) : "-"}
      </div>
      <div className="flex items-center justify-between mt-1">
        <ChangeBadge pct={idx.changePct} size="sm" />
        <Sparkline data={idx.spark} width={52} height={20} />
      </div>
    </div>
  );
}

function SectionTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-2.5">
      <h2 className="text-base font-bold">{children}</h2>
      {right}
    </div>
  );
}

function Sk({ w, h }: { w?: number; h: number }) {
  return <div className="skeleton shrink-0" style={{ width: w, height: h, flex: w ? undefined : 1 }} />;
}

function EmptyState({ updated }: { updated: string | null }) {
  return (
    <div className="card p-8 text-center mt-8">
      <div className="text-3xl mb-2">📭</div>
      <p className="font-semibold">아직 수집된 데이터가 없습니다</p>
      <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
        파이프라인이 처음 실행되면 이 화면이 채워집니다.
        {updated && <> 마지막 갱신: {updated}</>}
      </p>
    </div>
  );
}
