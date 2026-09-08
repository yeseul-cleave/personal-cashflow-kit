// fetch_kurly.mjs — Gmail의 컬리 주문접수 메일에서 품목/결제금액을 뽑는다. (파서 규칙: ggplab/banksalad-autobudget, MIT)
//   node scripts/fetch/fetch_kurly.mjs 2026_08
// 출력: private/enrich/kurly/<YYYY_MM>/컬리_주문_<YYYY_MM>.csv  (주문일, 총결제금액, 상품요약, 품목수, 메일제목)
import { launchGmail } from "./browser.mjs";
import { cfg, ENRICH, sleep, ymArg } from "./config.mjs";
import { mkdirSync } from "node:fs";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";

const ym = ymArg(process.argv[2]);
const [y, m] = ym.split("_").map(Number);
const after = `${y}/${String(m).padStart(2, "0")}/01`;
const before = m === 12 ? `${y + 1}/01/01` : `${y}/${String(m + 1).padStart(2, "0")}/01`;
const QUERY = `from:kurly.com subject:"주문이 정상적으로 접수" after:${after} before:${before}`;
const OUT = join(ENRICH, "kurly", ym);
mkdirSync(OUT, { recursive: true });

function parseKurly(text) {
  const sec = text.match(/구매상품 정보([\s\S]*?)상품금액/);
  const items = [];
  if (sec) {
    for (const line of sec[1].split("\n")) {
      const t = line.trim();
      if (t.startsWith("[") || /\d+\s*개$/.test(t)) items.push(t.replace(/\s+/g, " "));
    }
  }
  const am = text.match(/결제금액\s*:?\s*([\d,]+)\s*원/);
  return { items, total: am ? Number(am[1].replace(/,/g, "")) : 0 };
}
const csvCell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;

const { context, page } = await launchGmail({ headless: true });
await page.goto(`https://mail.google.com/mail/u/${cfg.gmailIndexKurly}/#search/` + encodeURIComponent(QUERY), { waitUntil: "domcontentloaded" });
await sleep(5000);
let prev = -1;
for (let s = 0; s < 8; s++) { const n = await page.locator("tr.zA").count(); if (n === prev) break; prev = n; await page.mouse.wheel(0, 4000); await sleep(1000); }
const rowCount = await page.locator("tr.zA").count();
console.log(`📬 컬리 메일 ${rowCount}건`);
const orders = [];
for (let i = 0; i < rowCount; i++) {
  const row = page.locator("tr.zA").nth(i);
  const subject = (await row.locator("span.bog").innerText().catch(() => "")) || "";
  await row.click(); await sleep(3000);
  const msgs = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll("div.a3s").forEach((body) => {
      const text = body.innerText || ""; if (!text.trim()) return;
      const c = body.closest("div.gs") || body.closest("div.adn");
      const dEl = (c && c.querySelector("span.g3")) || document.querySelector("span.g3");
      out.push({ date: dEl?.getAttribute("title") || dEl?.innerText || "", text });
    });
    return out;
  });
  for (const msg of msgs) {
    const p = parseKurly(msg.text);
    if (!p.total) continue;
    orders.push({ date: msg.date, total: p.total, items: p.items, subject });
    console.log(`  ${orders.length} ${msg.date}  ${p.total.toLocaleString()}원  품목 ${p.items.length}`);
  }
  await page.goBack(); await sleep(2000);
  await page.locator("tr.zA").first().waitFor({ timeout: 15000 }).catch(() => {});
}
await context.close();
const header = ["주문일", "총결제금액", "상품요약", "품목수", "메일제목"];
const lines = [header.map(csvCell).join(",")];
for (const o of orders) lines.push([o.date, o.total, o.items.join(" / "), o.items.length, o.subject].map(csvCell).join(","));
await writeFile(join(OUT, `컬리_주문_${ym}.csv`), "﻿" + lines.join("\n"));
console.log(`✅ 컬리 주문 ${orders.length}건 → ${OUT}`);
