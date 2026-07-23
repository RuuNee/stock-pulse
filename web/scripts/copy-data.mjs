// Copy the pipeline's data/ output into public/data so Vite serves it at /data/*.
// Runs before dev and build. Safe when data/ is absent (fresh checkout).
import { cp, mkdir, rm, access } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "..", "..", "data");
const dest = resolve(here, "..", "public", "data");

try {
  await access(src);
} catch {
  console.log("[copy-data] no data/ yet — skipping (site will show empty state)");
  process.exit(0);
}

await rm(dest, { recursive: true, force: true });
await mkdir(dest, { recursive: true });
await cp(src, dest, { recursive: true });
console.log(`[copy-data] copied ${src} -> ${dest}`);
