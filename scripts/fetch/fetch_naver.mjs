// fetch_naver.mjs — 네이버페이 결제내역(pay.naver.com/pc/history)을 월 단위로 수집.
//   node scripts/fetch/fetch_naver.mjs 2026_08
// 출력: private/enrich/naver/<YYYY_MM>/네이버페이_주문_<YYYY_MM>.csv  (날짜·상태·가맹점·상품명·금액·결제수단·주문번호)
// 세션: private/naver_auth.json (npm run login:naver). __NEXT_DATA__ JSON 파싱이라 셀렉터 불필요.
import { chromium } from "./deps.mjs";
import { cfg, ENRICH, sleep, ymArg } from "./config.mjs";
import { mkdirSync, existsSync } from "node:fs";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";

const ym = ymArg(process.argv[2]);
const authFile = cfg.naverAuth;
if (!existsSync(authFile)) { console.error("네이버 세션이 없습니다: npm run login:naver"); process.exit(1); }
const [y, m] = ym.split("_").map(Number);
const monthStart = new Date(y, m - 1, 1).getTime();
const monthEnd = new Date(m === 12 ? y + 1 : y, m === 12 ? 0 : m, 1).getTime();
const OUT_DIR = join(ENRICH, "naver", ym);
mkdirSync(OUT_DIR, { recursive: true });

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ storageState: authFile });
const page = await ctx.newPage();

// 로그인 계정 확인
await page.goto("https://pay.naver.com/pc/history?page=1", { waitUntil: "domcontentloaded", timeout: 30000 });
await sleep(2500);

function extractItems(nextData) {
  const out = [];
  const queries = nextData?.props?.pageProps?.dehydratedState?.queries ?? [];
  for (const q of queries) {
    if (q?.queryKey?.[0] !== "PAYMENT_LIST") continue;
    for (const pg of q?.state?.data?.pages ?? []) {
      for (const it of pg?.items ?? []) out.push(it);
    }
  }
  return out;
}

let naverId = "";
const seen = new Set();
const rows = [];
let stop = false;

for (let p = 1; p <= 60 && !stop; p++) {
  if (p > 1) {
    await page.goto(`https://pay.naver.com/pc/history?page=${p}`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await sleep(1800);
  }
  const nextData = await page.evaluate(() => {
    const el = document.getElementById("__NEXT_DATA__");
    return el ? JSON.parse(el.textContent) : null;
  });
  if (!nextData) { console.error(`p${p}: __NEXT_DATA__ 없음 (로그인 풀림?)`); break; }
  if (!naverId) {
    const qs = nextData?.props?.pageProps?.dehydratedState?.queries ?? [];
    naverId = qs.find((q) => q?.queryKey?.[0] === "MEMBER_PROFILE")?.state?.data?.naverId ?? "";
  }
  const items = extractItems(nextData);
  if (!items.length) { console.log(`p${p}: 아이템 없음 → 종료`); break; }

  let older = 0;
  for (const it of items) {
    if (seen.has(it._id)) continue;
    seen.add(it._id);
    const t = it.date;
    if (t < monthStart) { older++; continue; }
    if (t >= monthEnd) continue;
    const d = new Date(t);
    const ad = it.additionalData ?? {};
    rows.push({
      날짜: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`,
      시각: `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`,
      상태: it.status?.text ?? "",
      가맹점: it.merchantName ?? "",
      상품명: it.product?.name ?? "",
      금액: ad.orderAmount ?? it.product?.price ?? "",
      결제수단: ad.paymentMethod ?? "",
      주문번호: ad.orderNo ?? "",
      구분: it.serviceType ?? "",
    });
  }
  const dates = items.map((i) => i.date);
  console.log(`p${p}: ${items.length}건 (${new Date(Math.min(...dates)).toISOString().slice(0, 10)} ~ ${new Date(Math.max(...dates)).toISOString().slice(0, 10)}), 월내 누적 ${rows.length}`);
  if (older === items.length) stop = true;           // 페이지 전체가 대상월 이전 → 종료
}
await browser.close();

rows.sort((a, b) => (a.날짜 + a.시각 < b.날짜 + b.시각 ? -1 : 1));
const cols = ["날짜", "시각", "상태", "가맹점", "상품명", "금액", "결제수단", "주문번호", "구분"];
const esc = (v) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
const csv = "﻿" + [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
const outPath = join(OUT_DIR, `네이버페이_주문_${ym}.csv`);
await writeFile(outPath, csv);

console.log(`\n✅ 계정 ${naverId} — ${ym} 주문 ${rows.length}건`);
console.log(`→ ${outPath}`);
