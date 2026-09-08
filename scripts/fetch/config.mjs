// config.mjs — private/fetch.json 읽기 (+ 환경변수 우선)
import { readFileSync, existsSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import { ROOT } from "./deps.mjs";

export const PRIVATE = process.env.CASHFLOW_PRIVATE || join(ROOT, "private");
export const EXPORTS = join(PRIVATE, "exports");
export const ENRICH = join(PRIVATE, "enrich");
const cfgPath = join(PRIVATE, "fetch.json");
const raw = existsSync(cfgPath) ? JSON.parse(readFileSync(cfgPath, "utf8")) : {};
export const cfg = {
  gmailIndex: (process.env.GMAIL_INDEX ?? raw.gmail_index ?? "auto") === "" ? "auto" : String(process.env.GMAIL_INDEX ?? raw.gmail_index ?? "auto"),   // 없으면 auto: 뱅샐 메일 있는 계정을 찾는다
  gmailIndexCoupang: String(process.env.GMAIL_INDEX_COUPANG ?? raw.gmail_index_coupang ?? raw.gmail_index ?? 0),   // 쿠팡 메일이 다른 계정으로 오면
  gmailProfile: process.env.CASHFLOW_GMAIL_PROFILE || raw.gmail_profile || join(homedir(), ".personal-cashflow-gmail-profile"),
  zipPw: process.env.BANKSALAD_ZIP_PW || raw.banksalad_zip_password || "",
  mailCount: parseInt(process.env.BANKSALAD_MAIL_COUNT ?? raw.banksalad_mail_count ?? 1, 10),
  coupang: raw.coupang ?? true,
  kurly: raw.kurly ?? true,
  gmailIndexKurly: String(process.env.GMAIL_INDEX_KURLY ?? raw.gmail_index_kurly ?? raw.gmail_index_coupang ?? raw.gmail_index ?? 0),
  naver: raw.naver ?? false,
  naverAuth: join(PRIVATE, "naver_auth.json"),
};
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const ymArg = (s) => { if (!/^\d{4}_\d{2}$/.test(s || "")) { console.error("월은 YYYY_MM 형식 (예: 2026_08)"); process.exit(1); } return s; };

export function saveCfg(patch) {   // 감지한 값을 fetch.json 에 기억 (주석 키 _* 는 유지)
  mkdirSync(PRIVATE, { recursive: true });
  const cur = existsSync(cfgPath) ? JSON.parse(readFileSync(cfgPath, "utf8")) : {};
  writeFileSync(cfgPath, JSON.stringify({ ...cur, ...patch }, null, 2) + "\n");
}
