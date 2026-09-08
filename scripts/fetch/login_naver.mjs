// login_naver.mjs — 네이버 로그인 1회 → private/naver_auth.json 세션 저장 (크롬 창에서 직접 로그인)
// login.mjs — 네이버 로그인 1회 실행용.
// 브라우저가 뜨면 직접 로그인하세요. 로그인 완료를 자동 감지(네이버 인증 쿠키)해서
// 세션을 auth.json에 저장합니다. 다음부터는 이 세션을 재사용해 로그인 생략.

import { chromium } from "./deps.mjs";
import { cfg } from "./config.mjs";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
const AUTH_FILE = cfg.naverAuth; mkdirSync(dirname(AUTH_FILE), { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch({ headless: false });

let browserClosed = false;
browser.on("disconnected", () => { browserClosed = true; });

const context = await browser.newContext();
const page = await context.newPage();

await page.goto("https://nid.naver.com/nidlogin.login");

console.log("\n────────────────────────────────────────");
console.log("브라우저에서 네이버 로그인을 완료하세요.");
console.log("(아이디/비번 + 2단계 인증/캡차까지)");
console.log("⚠️ 로그인 끝날 때까지 창을 닫지 마세요!");
console.log("로그인되면 자동 감지해서 저장하고 창이 닫힙니다.");
console.log("최대 10분 기다립니다… (인증번호 천천히 하셔도 됨)");
console.log("────────────────────────────────────────\n");

// 네이버 로그인 성공 시 NID_AUT / NID_SES 쿠키가 생김 → 그걸로 완료 감지.
// 페이지가 닫혀도 context는 살아있으므로 context.cookies()로 폴링.
const DEADLINE = Date.now() + 10 * 60 * 1000;
let loggedIn = false;
while (Date.now() < DEADLINE) {
  if (browserClosed) {
    console.error("\n❌ 로그인 완료 전에 창이 닫혔어요. 다시 시도해주세요.\n");
    process.exit(1);
  }
  try {
    const cookies = await context.cookies();
    const names = new Set(cookies.map((c) => c.name));
    if (names.has("NID_AUT") && names.has("NID_SES")) {
      loggedIn = true;
      break;
    }
  } catch {
    // context 일시적 접근 실패 — 다음 루프에서 재시도
  }
  await sleep(2000);
}

if (!loggedIn) {
  console.error("\n❌ 5분 안에 로그인이 감지되지 않았어요. 다시 시도해주세요.\n");
  if (!browserClosed) await browser.close();
  process.exit(1);
}

await context.storageState({ path: AUTH_FILE });
console.log(`\n✅ 로그인 감지 + 세션 저장 완료 → ${AUTH_FILE}\n`);

if (!browserClosed) await browser.close();
