import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const DATA_DIR = resolve(fileURLToPath(new URL("..", import.meta.url)), "data");

const MIME: Record<string, string> = {
  ".json": "application/json; charset=utf-8",
};

/** dev 에서 `/data/*` 를 레포 `data/` 에서 직접 읽어 준다.
 *
 *  예전에는 `predev` 훅이 `data/` 를 `web/public/data/` 로 통째 복사했다. 복사는 서버를
 *  띄울 때 한 번뿐이라, 그 뒤 `git pull` 이나 로컬 파이프라인 실행으로 원본이 바뀌면
 *  화면은 옛 스냅샷에 멈춘 채 아무 표시도 없었다 — 2026-07-28 에 레포는 07-28 미장
 *  브리핑을 갖고 있는데 화면은 07-27 것을 보여주고 있었다. 없는 파일은 SPA fallback 이
 *  index.html 을 200 으로 돌려줘서 그것마저 조용했다. 사본을 없애면 이 상태가 없다.
 *
 *  배포는 정적 호스팅이라 사본이 필요하다 — `prebuild` 의 copy-data 는 그대로 둔다.
 */
function serveRepoData(): Plugin {
  return {
    name: "serve-repo-data",
    apply: "serve",
    configureServer(server) {
      // connect 가 "/data" 접두사를 떼고 넘겨준다 → req.url 은 "/manifest.json" 꼴.
      server.middlewares.use("/data", (req, res) => {
        // 여기서 항상 끝낸다. next() 로 흘리면 public/data 에 남은 옛 사본이 조용히
        // 응답해서, 없애려던 바로 그 침묵 실패가 되돌아온다.
        const path = decodeURIComponent((req.url ?? "/").split("?")[0]);
        const file = resolve(DATA_DIR, "." + path);
        if (!file.startsWith(DATA_DIR + sep)) {
          res.statusCode = 403;
          res.end("forbidden");
          return;
        }
        stat(file)
          .then((info) => {
            if (!info.isFile()) throw new Error("not a file");
            res.setHeader("Content-Type", MIME[extname(file)] ?? "application/octet-stream");
            res.setHeader("Cache-Control", "no-store");
            createReadStream(file).pipe(res);
          })
          .catch(() => {
            res.statusCode = 404;
            res.end("not found");
          });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), serveRepoData()],
  server: { port: 5173 },
});
