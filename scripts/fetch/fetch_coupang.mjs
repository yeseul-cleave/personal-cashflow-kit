// fetch_coupang.mjs — Gmail의 쿠팡 주문확인·멤버십·쿠페이취소 메일에서 품목/금액을 뽑는다.
//   node scripts/fetch/fetch_coupang.mjs 2026_08
// 출력: private/enrich/coupang/<YYYY_MM>/쿠팡_주문_<YYYY_MM>.csv · 쿠팡_품목_<YYYY_MM>.csv · raw/*.html
// 기존 gmail_coupang 수집기의 스레드 펼치기·할인 안분 로직을 사용한다.
import { launchGmail } from "./browser.mjs";
import { cfg, ENRICH, sleep, ymArg } from "./config.mjs";
import { mkdirSync } from "node:fs";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";

const ym = ymArg(process.argv[2]);
const [y, m] = ym.split("_").map(Number);
const after = `${y}/${String(m).padStart(2, "0")}/01`;
const before = m === 12 ? `${y + 1}/01/01` : `${y}/${String(m + 1).padStart(2, "0")}/01`;
const QUERIES = [
  `from:coupang after:${after} before:${before}`,
  `from:kcp.co.kr subject:취소 after:${after} before:${before}`,
];
const OUT = join(ENRICH, "coupang", ym);
const RAW = join(OUT, "raw");
mkdirSync(RAW, { recursive: true });

const amountRe = /^-?[\d,]+원$/;
const won = (s) => Number(String(s ?? "").replace(/[^\d-]/g, "")) || 0; // "104,300 원" → 104300
const fmt = (n) => n.toLocaleString("en-US") + "원";                    // -28800 → "-28,800원"

// 와우멤버십 월회비 메일에서 결제금액 추출 ("결제금액" 라벨 근처 첫 금액)
function feeFromMembership(text) {
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes("결제금액")) {
      const near = [lines[i].split("\t").slice(1).join(" "), lines[i + 1], lines[i + 2]].join(" ");
      const m = near.match(/-?[\d,]+\s*원/);
      if (m) return m[0].replace(/\s/g, "");
    }
  }
  return "";
}

// NHN KCP 쿠페이 결제취소 메일 파싱 (label\t값 구조)
function parseCancel(text) {
  const lines = text.split("\n");
  const find = (pred) => {
    for (const line of lines) {
      const f = line.split("\t");
      if (f.length >= 2 && pred(f[0].trim()) && f[1].trim()) return f[1].trim();
    }
    return "";
  };
  return {
    cancelAmt: find((l) => l.includes("취소금액")),   // 부분취소금액 / 취소금액
    origAmt: find((l) => l === "결제금액"),
    payDate: find((l) => l === "결제일시"),
    cancelDate: find((l) => l === "취소요청일시"),
    card: find((l) => l === "카드종류"),
    halbu: find((l) => l === "할부기간"),
    orderNo: find((l) => l === "주문번호"),
    product: find((l) => l === "주문상품명"),
  };
}

function parseOrder(text) {
  const lines = text.split("\n").map((l) => l.replace(/\r$/, ""));
  const items = [];
  for (const line of lines) {
    const f = line.split("\t");
    if (
      f.length >= 5 &&
      amountRe.test(f[1].trim()) &&
      /^\d+$/.test(f[2].trim()) &&
      amountRe.test(f[3].trim())
    ) {
      items.push({
        name: f[0].trim(),
        unit: f[1].trim(),
        qty: f[2].trim(),
        amount: f[3].trim(),
        seller: f.slice(4).join(" ").trim(),
      });
    }
  }
  const find = (label) => {
    for (const line of lines) {
      const f = line.split("\t");
      if (f[0].trim() === label && f[1] !== undefined && f[1].trim() !== "") return f[1].trim();
    }
    return "";
  };
  const known = new Set(["상품 가격", "할인금액", "배송비", "총 결제금액"]);
  let pay = "";
  for (const line of lines) {
    const f = line.split("\t");
    if (f.length === 2 && amountRe.test(f[1].trim()) && !known.has(f[0].trim()) && f[0].includes("/")) {
      pay = f[0].trim();
    }
  }
  return {
    items,
    total: find("총 결제금액"),
    goods: find("상품 가격"),
    discount: find("할인금액"),
    ship: find("배송비"),
    pay,
    recipient: find("받으시는 분"),
  };
}

// 메일 본문 텍스트 1건 → 분류(주문/멤버십/취소/기타) + 파싱결과
function classifyMsg(text, subject) {
  const isCancel = /취소요청일시|부분취소금액|결제취소|취소금액/.test(text);
  if (isCancel) {
    const c = parseCancel(text);
    return {
      tag: "취소",
      parsed: {
        items: [],
        total: c.cancelAmt ? fmt(-Math.abs(won(c.cancelAmt))) : "",
        goods: "", discount: "", ship: "",
        pay: [c.card, c.halbu].filter(Boolean).join(" / "),
        recipient: "",
        cancel: c,
      },
    };
  }
  const parsed = parseOrder(text);
  if (parsed.items.length > 0) return { tag: "주문", parsed };
  if (subject.includes("멤버십") || subject.includes("월회비") || /와우 멤버십|월회비/.test(text)) {
    parsed.total = feeFromMembership(text);
    return { tag: "멤버십", parsed };
  }
  return { tag: "기타", parsed };
}

const csvCell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
const safeName = (s) => s.replace(/[\/\\:*?"<>|]/g, "_").slice(0, 40);

const { context, page } = await launchGmail({ headless: true });
const orders = [];
let idx = 0;

for (const q of QUERIES) {
  const url = `https://mail.google.com/mail/u/${cfg.gmailIndexCoupang}/#search/` + encodeURIComponent(q);
  console.log("\n검색:", q);
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await sleep(6000);

  // 목록을 스크롤해 가능한 많이 로드
  let prev = -1;
  for (let s = 0; s < 8; s++) {
    const n = await page.locator("tr.zA").count();
    if (n === prev) break;
    prev = n;
    await page.mouse.wheel(0, 4000);
    await sleep(1200);
  }
  const rowCount = await page.locator("tr.zA").count();
  console.log(`📬 ${rowCount}건`);

  for (let i = 0; i < rowCount; i++) {
    const row = page.locator("tr.zA").nth(i);
    const subject = (await row.locator("span.bog").innerText().catch(() => "")) || "";
    await row.click();
    await sleep(3500);

    // ── 대화(스레드) 내 접힌 메일 모두 펼치기 ──────────────────
    //  쿠팡 주문확인 메일은 제목이 전부 동일 → Gmail이 한 대화로 묶음(예: "쿠팡 2").
    //  접힌 메일을 펼치지 않으면 스레드당 1건만 읽혀 주문이 누락된다.
    for (let r = 0; r < 8; r++) {
      let acted = false;
      const expandAll = page.locator(
        '[aria-label="모두 펼치기"],[data-tooltip="모두 펼치기"],[aria-label="Expand all"],[data-tooltip="Expand all"]'
      );
      if (await expandAll.count().catch(() => 0)) {
        await expandAll.first().click().catch(() => {});
        acted = true;
        await sleep(700);
      }
      const sup = page.locator(".adx"); // "메시지 N개 더보기" 슈퍼접힘 블록
      for (let k = 0; k < (await sup.count().catch(() => 0)); k++) {
        const el = sup.nth(k);
        if (await el.isVisible().catch(() => false)) { await el.click().catch(() => {}); acted = true; await sleep(400); }
      }
      const col = page.locator(".kv, .kQ"); // 개별 접힌 메일 헤더
      for (let k = 0; k < (await col.count().catch(() => 0)); k++) {
        const el = col.nth(k);
        if (await el.isVisible().catch(() => false)) { await el.click().catch(() => {}); acted = true; await sleep(300); }
      }
      if (!acted) break;
      await sleep(500);
    }

    // ── 스레드 내 모든 메시지 본문 추출 (메시지별 날짜 포함) ──
    let msgs = await page.evaluate(() => {
      const out = [];
      const seen = new Set();
      document.querySelectorAll("div.a3s").forEach((body) => {
        const text = body.innerText || "";
        if (!text.trim()) return;
        const key = text.length + "|" + text.slice(0, 60);
        if (seen.has(key)) return;
        seen.add(key);
        const c = body.closest("div.gs") || body.closest("div.adn");
        const dEl = (c && c.querySelector("span.g3")) || document.querySelector("span.g3");
        const date = dEl?.getAttribute("title") || dEl?.innerText || "";
        out.push({ date, text, html: body.outerHTML || "" });
      });
      return out;
    });
    if (msgs.length === 0) msgs = [{ date: "", text: "", html: "" }];

    for (const msg of msgs) {
      const { tag, parsed } = classifyMsg(msg.text, subject);
      idx++;
      console.log(`  ${idx} [${tag}] ${msg.date}  ${subject}  → 품목 ${parsed.items.length}, 총 ${parsed.total || "-"}`);
      const fn = `${String(idx).padStart(2, "0")}_${tag}_${safeName(subject)}.html`;
      await writeFile(join(RAW, fn), msg.html);
      orders.push({ date: msg.date, subject, tag, ...parsed, rawFile: `raw/${fn}` });
    }

    await page.goBack();
    await sleep(2500);
    await page.locator("tr.zA").first().waitFor({ timeout: 15000 }).catch(() => {});
  }
}

// 주문별로 할인 안분 실결제금액 계산 (구매금액 비율, 합이 총결제금액과 정확히 일치)
for (const o of orders) {
  const total = won(o.total);
  const sumItems = o.items.reduce((a, it) => a + won(it.amount), 0);
  let acc = 0;
  o.items.forEach((it, idx) => {
    if (!total || !sumItems) { it.alloc = won(it.amount); return; }
    if (idx < o.items.length - 1) {
      it.alloc = Math.round((won(it.amount) / sumItems) * total);
      acc += it.alloc;
    } else {
      it.alloc = total - acc; // 마지막 품목으로 끝수 보정 → 합 == 총결제금액
    }
  });
}

// CSV 1: 품목 단위 (안분실결제 = 카드결제액과 합이 맞는 실제 낸 돈)
const itemHeader = ["주문일", "구분", "상품명", "수량", "구매금액", "안분실결제", "판매자", "주문총액", "결제수단", "받는사람", "메일제목"];
const itemRows = [itemHeader.map(csvCell).join(",")];
for (const o of orders) {
  if (o.items.length === 0) {
    const nm = o.tag === "취소" ? "[취소] " + (o.cancel?.product || "")
             : o.tag === "멤버십" ? "와우 멤버십 월회비"
             : "(품목없음)";
    const seller = o.tag === "취소" ? `원주문 ${o.cancel?.origAmt || ""} / ${o.cancel?.orderNo || ""}` : "";
    itemRows.push([o.date, o.tag, nm, "", o.total, o.total, seller, o.total, o.pay, o.recipient, o.subject].map(csvCell).join(","));
  }
  for (const it of o.items) {
    itemRows.push([o.date, o.tag, it.name, it.qty, it.amount, it.alloc, it.seller, o.total, o.pay, o.recipient, o.subject].map(csvCell).join(","));
  }
}
await writeFile(join(OUT, `쿠팡_품목_${ym}.csv`), "﻿" + itemRows.join("\n"));

// CSV 2: 주문 단위 요약
const ordHeader = ["주문일", "구분", "상품수", "상품가격", "할인금액", "배송비", "총결제금액", "결제수단", "받는사람", "상품요약", "메일제목", "증빙파일"];
const ordRows = [ordHeader.map(csvCell).join(",")];
for (const o of orders) {
  const summary = o.tag === "취소" ? `[취소] ${o.cancel?.product || ""} (원주문 ${o.cancel?.origAmt || ""})`
                : o.tag === "멤버십" ? "와우 멤버십 월회비"
                : o.items.map((x) => x.name).join(" / ");
  ordRows.push([o.date, o.tag, o.items.length, o.goods, o.discount, o.ship, o.total, o.pay, o.recipient, summary, o.subject, o.rawFile].map(csvCell).join(","));
}
await writeFile(join(OUT, `쿠팡_주문_${ym}.csv`), "﻿" + ordRows.join("\n"));

const orderCnt = orders.filter((o) => o.tag === "주문").length;
console.log(`\n✅ 완료`);
console.log(`   주문 ${orderCnt}건 / 전체 ${orders.length}건`);
console.log(`   → ${OUT}`);
console.log(`     쿠팡_품목_${ym}.csv`);
console.log(`     쿠팡_주문_${ym}.csv`);
console.log(`     raw/ (본문 HTML 증빙 ${orders.length}개)`);

await sleep(2000);
await context.close();
