// login_gmail.mjs — Gmail 세션 확인/저장.
//   node scripts/fetch/login_gmail.mjs          이미 로그인돼 있으면 아무것도 안 하고 종료(0). 아니면 크롬 창을 띄워 로그인 대기.
//   node scripts/fetch/login_gmail.mjs --check  확인만 (로그인돼 있으면 0, 아니면 1). 창 안 띄움.
import { launchGmail } from "./browser.mjs";
import { cfg, sleep } from "./config.mjs";

const checkOnly = process.argv.includes("--check");

async function loggedIn(page) {
  try {
    await page.goto("https://mail.google.com/mail/u/0/", { waitUntil: "domcontentloaded", timeout: 30000 });
    for (let i = 0; i < 10; i++) {
      const url = page.url();
      if (url.includes("accounts.google.com")) return false;
      const n = await page.locator('input[aria-label*="검색"], input[aria-label*="Search"]').count().catch(() => 0);
      if (n > 0) return true;
      await sleep(1000);
    }
  } catch {}
  return false;
}

{ // 1) 조용히 확인
  const { context, page } = await launchGmail({ headless: true });
  const ok = await loggedIn(page);
  await context.close();
  if (ok) { console.log("✅ Gmail 로그인 상태 (세션 있음)"); process.exit(0); }
  if (checkOnly) { console.log("Gmail 로그인 필요"); process.exit(1); }
}
// 2) 창 띄워 로그인 대기
const { context, page } = await launchGmail();
let closed = false; context.on("close", () => { closed = true; });
await page.goto("https://mail.google.com/mail/u/0/");
console.log("\n🔑 크롬 창에서 Gmail 로그인하세요. 받은편지함이 뜨면 자동 저장됩니다 (최대 10분).\n");
const DEADLINE = Date.now() + 10 * 60 * 1000; let ok = false;
while (Date.now() < DEADLINE) {
  if (closed) { console.error("로그인 전에 창이 닫혔어요."); process.exit(1); }
  try {
    const url = page.url();
    if (url.includes("mail.google.com/mail") && !url.includes("accounts.google.com")) {
      const n = await page.locator('input[aria-label*="검색"], input[aria-label*="Search"]').count().catch(() => 0);
      if (n > 0) { await sleep(2000); ok = true; break; }
    }
  } catch {}
  await sleep(2000);
}
if (!ok) { console.error("10분 안에 로그인이 감지되지 않았어요."); if (!closed) await context.close(); process.exit(1); }
console.log("✅ Gmail 로그인 저장 완료"); if (!closed) await context.close();
