import { api } from "../lib/api";
import { timeAgo } from "../lib/format";
import { useAsync } from "../lib/useAsync";

// pulse 워크플로가 2시간마다 data/ 를 갱신한다. 다만 GitHub 스케줄러 지연이 실측
// 6~202분이라 정상 동작 중에도 갱신 간격이 5시간 넘게 벌어질 수 있다. 헛경보가
// 침묵보다 나쁘므로(Brief.tsx 의 StaleNotice 와 같은 판단) 여유를 두고 6시간에서 알린다.
export const STALE_AFTER_MS = 6 * 60 * 60 * 1000;

/** `generatedAt` 이 낡았으면 경과 밀리초, 아니면 null. */
export function staleAge(generatedAt: string | undefined, now: number = Date.now()): number | null {
  if (!generatedAt) return null;
  const then = new Date(generatedAt).getTime();
  if (Number.isNaN(then)) return null;
  // 음수는 시계가 어긋난 것이다 — 그걸 "낡았다"고 부를 수는 없다.
  const age = now - then;
  return age > STALE_AFTER_MS ? age : null;
}

/** 화면에 보이는 데이터가 통째로 낡았을 때 알린다.
 *
 *  로컬에서는 `data/` 를 직접 읽으므로(vite.config.ts 의 serveRepoData) 원본 자체가
 *  낡았다는 뜻이다 — 한동안 `git pull` 을 안 했거나 파이프라인을 안 돌린 것이다.
 *  배포본에서는 파이프라인이 멈췄다는 뜻이다. 둘 다 "겉보기엔 멀쩡한데 내용만 낡은"
 *  상태라 화면이 직접 말해 주지 않으면 알아채기 어렵다. */
export default function StaleBanner() {
  // manifest 를 못 읽으면 아무것도 띄우지 않는다 — 각 페이지가 자기 에러를 이미 보여준다.
  const { data } = useAsync(() => api.manifest(), []);
  const generatedAt = data?.generatedAt;
  if (staleAge(generatedAt) === null) return null;

  return (
    <div
      className="card p-3 mb-4 text-sm leading-relaxed"
      style={{ borderColor: "var(--warn, #b45309)", background: "var(--surface-2)" }}
      role="status"
    >
      ⚠️ <b>데이터가 {timeAgo(generatedAt)} 것입니다.</b>
      <div className="mt-1" style={{ color: "var(--muted)" }}>
        {import.meta.env.DEV ? (
          <>
            로컬 <code>data/</code> 가 낡았습니다. <code>git pull</code> 로 최신 데이터를 받거나{" "}
            <code>python -m pipeline.run pulse</code> 를 돌리세요.
          </>
        ) : (
          "자동 갱신이 멈췄을 수 있어요. 시세와 뉴스가 실제보다 오래된 내용일 수 있습니다."
        )}
      </div>
    </div>
  );
}
