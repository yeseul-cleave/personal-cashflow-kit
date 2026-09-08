// browser.mjs — 진짜 크롬 + 전용 프로필 (Gmail 세션 영구 저장 → 로그인 1회)
import { chromium } from "./deps.mjs";
import { cfg } from "./config.mjs";

export async function launchGmail({ headless = false } = {}) {
  const context = await chromium.launchPersistentContext(cfg.gmailProfile, {
    channel: "chrome", headless, viewport: null,
    args: ["--disable-blink-features=AutomationControlled", "--start-maximized"],
    ignoreDefaultArgs: ["--enable-automation"],
  });
  await context.addInitScript(() => { Object.defineProperty(navigator, "webdriver", { get: () => undefined }); });
  const page = context.pages()[0] ?? (await context.newPage());
  return { context, page };
}
