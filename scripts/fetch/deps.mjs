// deps.mjs — playwright 로더. 킷 루트에서 `npm install` 했으면 그걸 쓰고,
// 없으면 홈의 공용 설치(~/.personal-cashflow-deps 또는 ~/.naver-receipts-deps)를 찾는다.
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const candidates = [join(ROOT, "noop.js"), join(homedir(), ".personal-cashflow-deps", "noop.js"), join(homedir(), ".naver-receipts-deps", "noop.js")];
let playwright = null;
for (const c of candidates) {
  try { playwright = createRequire(c)("playwright"); break; } catch {}
}
if (!playwright) {
  console.error("playwright 가 없습니다. 킷 루트에서 `npm install` 을 실행하세요.");
  process.exit(1);
}
export const { chromium } = playwright;
export { ROOT };
