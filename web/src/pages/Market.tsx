import { useParams, Link, Navigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import MoodCard from "../components/MoodCard";
import ChangeBadge from "../components/ChangeBadge";
import Sparkline from "../components/Sparkline";
import { fmtMarcap, fmtPrice } from "../lib/format";
import type { Market as Mkt, Sector, MoverRef, TickerIndexEntry } from "../lib/types";

export default function Market() {
  const { market } = useParams<{ market: string }>();
  const m = (market?.toUpperCase() as Mkt) ?? "KR";
  if (m !== "KR" && m !== "US") return <Navigate to="/" replace />;

  const overview = useAsync(() => api.overview(), [m]);
  const tickers = useAsync(() => api.tickers(), []);

  const ov = overview.data;
  const list = (tickers.data ?? []).filter((t) => t.market === m);
  const title = m === "KR" ? "국장 (국내)" : "미장 (미국)";
  // 목록의 모든 가격이 같은 날 종가다. 행마다 날짜를 붙이면 시끄러우니
  // 제목 옆에 한 번만 적는다. 없으면 사용자가 오늘 값으로 읽는다.
  const asOf = list.reduce<string | null>(
    (latest, t) => (t.date && (!latest || t.date > latest) ? t.date : latest), null);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-baseline gap-2 flex-wrap">
        <h1 className="text-2xl font-bold">{title}</h1>
        {asOf && (
          <span className="text-sm tabular-nums" style={{ color: "var(--muted)" }}>
            {asOf} 마감 기준
          </span>
        )}
      </div>

      {ov?.marketMood[m] && <MoodCard title={m === "KR" ? "국내" : "미국"} mood={ov.marketMood[m]} />}

      {/* macro strip */}
      {ov && (
        <div className="scroll-x -mx-1 px-1">
          <div className="flex gap-2 pb-1" style={{ minWidth: "min-content" }}>
            {ov.indices
              .filter((i) => i.market === m || i.market === "GLOBAL")
              .map((i) => (
                <div key={i.key} className="card px-3 py-2 shrink-0">
                  <div className="text-xs" style={{ color: "var(--muted)" }}>{i.name}</div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold tabular-nums text-sm">
                      {i.value != null ? i.value.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) : "-"}
                    </span>
                    <ChangeBadge pct={i.changePct} size="sm" />
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* sector heatmap */}
      {ov?.sectors[m]?.length ? (
        <section>
          <h2 className="text-base font-bold mb-2.5">섹터 히트맵</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {ov.sectors[m].map((sct) => <SectorTile key={sct.name} s={sct} />)}
          </div>
        </section>
      ) : null}

      {/* movers */}
      {ov && (
        <div className="grid sm:grid-cols-2 gap-4">
          <MoverList title="🔺 상승 상위" market={m} rows={ov.movers[m]?.up ?? []} />
          <MoverList title="🔻 하락 상위" market={m} rows={ov.movers[m]?.down ?? []} />
        </div>
      )}

      {/* full list */}
      <section>
        <h2 className="text-base font-bold mb-2.5">전체 종목</h2>
        <div className="card divide-y" style={{ borderColor: "var(--border)" }}>
          {/* 로딩·실패·빈 데이터를 구분한다. 예전엔 셋 다 "로딩 중"으로 보여서
              데이터가 실제로 비었을 때 원인을 알 수 없었다. */}
          {tickers.loading ? (
            <div className="p-6 text-center text-sm" style={{ color: "var(--muted)" }}>데이터 로딩 중…</div>
          ) : tickers.error ? (
            <div className="p-6 text-center text-sm" style={{ color: "var(--muted)" }}>
              데이터를 불러오지 못했습니다.
            </div>
          ) : list.length ? (
            list.map((t) => <TickerRow key={t.code} t={t} />)
          ) : (
            <div className="p-6 text-center text-sm" style={{ color: "var(--muted)" }}>
              {title} 종목 데이터가 아직 없습니다.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function SectorTile({ s }: { s: Sector }) {
  const up = s.changePct >= 0;
  return (
    <div className="card p-3" style={{ borderColor: up ? "var(--up)" : "var(--down)" }}>
      <div className="font-semibold text-sm">{s.name}</div>
      <ChangeBadge pct={s.changePct} size="sm" />
      <div className="text-xs mt-1 truncate" style={{ color: "var(--muted)" }}>
        {s.count}종목 · 대표 {s.topName}
      </div>
    </div>
  );
}

function MoverList({ title, market, rows }: { title: string; market: Mkt; rows: MoverRef[] }) {
  return (
    <div className="card p-3">
      <h3 className="text-sm font-bold mb-2">{title}</h3>
      <div className="flex flex-col">
        {rows.map((r) => (
          <Link key={r.code} to={`/ticker/${market}/${r.code}`} className="flex items-center justify-between py-1.5">
            <span className="text-sm truncate">{r.name}</span>
            <ChangeBadge pct={r.changePct} size="sm" />
          </Link>
        ))}
        {!rows.length && <span className="text-sm py-2" style={{ color: "var(--muted)" }}>-</span>}
      </div>
    </div>
  );
}

function TickerRow({ t }: { t: TickerIndexEntry }) {
  return (
    <Link to={`/ticker/${t.market}/${t.code}`} className="flex items-center gap-3 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-sm truncate">
          {t.name}
          {t.eventCount > 0 && (
            <span className="ml-1.5 text-xs" style={{ color: "var(--accent)" }}>📍{t.eventCount}</span>
          )}
        </div>
        <div className="text-xs" style={{ color: "var(--muted)" }}>
          {t.sector} · {fmtMarcap(t.marcap, t.currency)}
        </div>
      </div>
      <Sparkline data={t.spark} width={64} height={26} />
      <div className="text-right shrink-0" style={{ minWidth: 90 }}>
        <div className="text-sm font-semibold tabular-nums">{fmtPrice(t.close, t.currency)}</div>
        <ChangeBadge pct={t.changePct} size="sm" />
      </div>
    </Link>
  );
}
