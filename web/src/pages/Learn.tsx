import { TERMS } from "../lib/terms";

const GROUPS: { title: string; keys: string[] }[] = [
  { title: "기본 용어", keys: ["marcap", "volume", "amount", "per", "pbr", "roe", "eps", "dividend", "etf"] },
  { title: "차트 보는 법", keys: ["ma", "goldencross", "deadcross", "rsi", "gap", "zscore"] },
  { title: "시장 구조", keys: ["kospi", "kosdaq", "sp500", "nasdaq", "dow", "circuit", "short"] },
  { title: "거시 경제", keys: ["fx", "rate", "ytnx", "inflation", "fomc", "vix", "foreign", "institution"] },
  { title: "실적·이벤트", keys: ["earning", "guidance"] },
];

export default function Learn() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold">주식 용어 사전</h1>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          모르는 단어가 나오면 여기서 찾아보세요. 쉬운 말로 풀어 설명합니다.
        </p>
      </div>

      {GROUPS.map((g) => (
        <section key={g.title}>
          <h2 className="text-base font-bold mb-2.5">{g.title}</h2>
          <div className="grid sm:grid-cols-2 gap-2.5">
            {g.keys.map((k) => {
              const e = TERMS[k];
              if (!e) return null;
              return (
                <div key={k} className="card p-3.5">
                  <div className="font-semibold text-sm">{e.title}</div>
                  <p className="mt-1 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>{e.short}</p>
                  {e.more && <p className="mt-1 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>{e.more}</p>}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
