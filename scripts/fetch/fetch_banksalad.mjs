// fetch_banksalad.mjs — Gmail에서 뱅크샐러드 "파일로 받기" zip을 찾아 private/exports/ 에 푼다. 묻지 않는다.
//   node scripts/fetch/fetch_banksalad.mjs [--wait]
//   - Gmail 계정 번호(u/N)는 fetch.json 에 없으면 0~4를 훑어 뱅샐 메일이 있는 계정을 찾고 fetch.json 에 기억한다.
//   - 메일이 없으면 안내 후 종료(2). --wait 면 15분 동안 30초마다 다시 본다 (사용자가 앱에서 내보내는 동안).
//   - 압축 비밀번호가 없으면 빈 비번으로 풀어 보고, 실패하면 zip 을 남겨두고 종료(3) → 비번 넣고 다시 실행하면 다운로드 없이 푼다.
// 종료코드: 0 성공 · 1 로그인 필요 · 2 뱅샐 메일 없음 · 3 압축 비밀번호 필요
import { launchGmail } from "./browser.mjs";
import { cfg, EXPORTS, PRIVATE, sleep, saveCfg } from "./config.mjs";
import { writeFileSync, mkdirSync, readdirSync, unlinkSync } from "node:fs";
import { execSync } from "node:child_process";
import { join } from "node:path";

const WAIT = process.argv.includes("--wait");
mkdirSync(EXPORTS, { recursive: true });

function tryUnzip(zp, pw) {
  try { execSync(`unzip -o -P '${pw}' '${zp}' -d '${EXPORTS}'`, { stdio: "pipe" }); return true; } catch { return false; }
}
function unzipAll() {
  const zips = readdirSync(EXPORTS).filter((f) => f.toLowerCase().endsWith(".zip"));
  let ok = 0, need = false;
  for (const z of zips) {
    const zp = join(EXPORTS, z);
    if (tryUnzip(zp, cfg.zipPw || "")) { unlinkSync(zp); ok++; console.log(`🔓 ${z} → exports/`); }
    else need = true;
  }
  return { ok, need };
}

// 0) 이미 받아둔 zip 이 있으면 (비번만 없었던 경우) 먼저 풀어 본다
{
  const { ok, need } = unzipAll();
  if (ok && !need) { console.log(`✅ 기존 zip ${ok}개 해제 완료 → ${EXPORTS}`); process.exit(0); }
  if (need) { console.error("🔒 압축 비밀번호가 필요합니다. private/fetch.json 의 banksalad_zip_password 에 넣고 다시 실행하세요 (다운로드는 다시 안 합니다)."); process.exit(3); }
}

const { context, page } = await launchGmail({ headless: true });

async function rowsAt(idx) {
  await page.goto(`https://mail.google.com/mail/u/${idx}/#search/from%3Abanksalad`, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  if (page.url().includes("accounts.google.com")) return null;          // 로그인 안 됨
  for (let i = 0; i < 12; i++) { if ((await page.$$("tr.zA")).length) break; await sleep(1000); }
  return await page.$$("tr.zA");
}

// 1) 계정 번호 찾기
let idx = cfg.gmailIndex;                        // 숫자 문자열 또는 "auto"
let rows = null;
const candidates = idx === "auto" ? ["0", "1", "2", "3", "4"] : [idx];
for (const c of candidates) {
  const r = await rowsAt(c);
  if (r === null) { console.error("🔑 Gmail 로그인이 필요합니다: node scripts/fetch/login_gmail.mjs"); await context.close(); process.exit(1); }
  if (r.length) { idx = c; rows = r; break; }
  if (candidates.length > 1) {
    const title = await page.title().catch(() => "");
    if (!title || /Gmail$/.test(title) === false && title.includes("찾을 수 없")) break;
  }
}
if (!rows || !rows.length) {
  console.log("📭 뱅크샐러드 메일이 없습니다. 앱 → 마이 → 데이터 내보내기 → 파일로 받기 (기간: 최근 1년) 을 해 주세요.");
  if (!WAIT) { await context.close(); process.exit(2); }
  console.log("   15분 동안 30초마다 다시 확인합니다…");
  const deadline = Date.now() + 15 * 60 * 1000;
  while (Date.now() < deadline && !(rows && rows.length)) {
    await sleep(30000);
    for (const c of candidates) { const r = await rowsAt(c); if (r && r.length) { idx = c; rows = r; break; } }
  }
  if (!rows || !rows.length) { console.error("⏰ 15분 안에 메일이 오지 않았습니다."); await context.close(); process.exit(2); }
}
if (cfg.gmailIndex === "auto") saveCfg({ gmail_index: Number(idx) });
console.log(`📬 Gmail u/${idx} — 뱅크샐러드 메일 ${rows.length}건, 최신 ${Math.min(cfg.mailCount, rows.length)}건 처리`);

// 2) 첨부 다운로드
let downloaded = [];
const n = Math.min(cfg.mailCount, rows.length);
for (let m = 0; m < n; m++) {
  rows = await page.$$("tr.zA"); await rows[m].click();
  for (let i = 0; i < 25; i++) { if ((await page.$$("[download_url]")).length) break; await sleep(1000); }
  const atts = await page.$$eval("[download_url]", (els) => els.map((e) => e.getAttribute("download_url")));
  for (const a of atts) {
    const i1 = a.indexOf(":"), i2 = a.indexOf(":", i1 + 1);
    const name = decodeURIComponent(a.slice(i1 + 1, i2));
    let url = a.slice(i2 + 1); const last = url.lastIndexOf("https://"); if (last > 0) url = url.slice(last);
    const buf = await (await context.request.get(url)).body();
    const zp = join(EXPORTS, name); writeFileSync(zp, buf); downloaded.push(name);
    console.log(`⬇️  ${name} (${buf.length.toLocaleString()} bytes)`);
  }
  if (m < n - 1) { await page.goBack({ waitUntil: "domcontentloaded" }); for (let i = 0; i < 25; i++) { if ((await page.$$("tr.zA")).length) break; await sleep(1000); } }
}
await context.close();

// 3) 해제
const { ok, need } = unzipAll();
if (need) { console.error("🔒 압축 비밀번호가 필요합니다. private/fetch.json 의 banksalad_zip_password 에 넣고 다시 실행하세요 (다운로드는 다시 안 합니다)."); process.exit(3); }
console.log(ok ? `✅ export ${ok}개 → ${EXPORTS}` : "⚠️ 첨부에 zip 이 없었습니다.");
