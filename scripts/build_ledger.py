#!/usr/bin/env python3
"""1단계: export + profile.yaml + rules.csv + overrides.csv → private/ledger/ledger.csv

사용:  python3 scripts/build_ledger.py [export.xlsx ...]
출력:  private/ledger/ledger.csv        거래 단위 장부 (귀속·카테고리·고정비·상태·근거)
       private/setup/03_확인필요.md     아직 못 정한 거래 묶음 (AI가 이걸 보고 묻는다)

멱등: 몇 번 돌려도 같은 결과. 사람의 답은 rules.csv(가맹점 단위) 또는
overrides.csv(거래 한 건 단위)에만 쌓이고, 이 스크립트는 그걸 읽어 다시 만든다.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import timedelta

import yaml

from common import (LEDGER, SETUP, TEMPLATES, Tx, find_exports, load_enrichment, load_overrides, load_profile,
                    load_rules, load_suggestions, load_transactions, match_enrichment, normalize_merchant, tx_key, won)

INCOME_CATS = {"수입", "입금", "기타입금", "매출", "급여"}        # 룰에서 이 카테고리면 수입으로 정규화
CAPITAL_CATS = {"자산거래"}                                       # 부동산·보증금·대출 실행/상환 = 현금흐름 아님

MARKET_KW = ("쿠팡", "네이버페이", "네이버", "토스쇼핑", "11번가", "G마켓", "옥션", "SSG", "당근페이")   # 가맹점이 장터라 품목으로 다시 본다

LEDGER_COLS = ["날짜", "시간", "월", "귀속", "계좌", "계좌성격", "타입", "내용", "품목", "금액",
               "카테고리", "세부", "고정비", "상태", "근거", "거래키"]

# 뱅샐 대분류 → 우리 카테고리 보정
BS_CAT_MAP = {"금융수입": ("수입", "이자·배당"), "급여": ("수입", "급여"), "용돈": ("수입", "용돈"),
              "카드대금": ("내부이체", "카드대금"), "저축": ("내부이체", "저축·투자 이체"),
              "투자": ("내부이체", "저축·투자 이체"), "현금": ("내부이체", "현금인출"),
              "이체": ("내부이체", "계좌간이동"), "대출": ("세금/수수료", "대출상환")}


def main(argv: list[str]) -> None:
    files = find_exports(argv[1:] or None)
    # 여러 export가 기간이 겹치면 같은 거래를 파일 간에만 제거 (한 파일 안의 같은 분 두 번 송금은 진짜다)
    txs: list[Tx] = []
    seen: set = set()
    for f in files:
        for t in load_transactions(f):
            k = (t.date, t.time, t.account, t.desc, t.amount)
            if k in seen and f is not files[0]:
                continue
            txs.append(t)
        seen |= {(t.date, t.time, t.account, t.desc, t.amount) for t in txs}
    txs.sort(key=lambda t: (t.date, t.time, t.idx))

    prof = load_profile()
    rules = load_rules()
    overrides = load_overrides()
    with open(TEMPLATES / "categories.yaml", encoding="utf-8") as f:
        cats = yaml.safe_load(f)
    fixed_subs = set(cats.get("fixed_subs", []))

    members = {m["id"]: m for m in prof["household"]["members"]}
    accounts = {a["name"]: a for a in prof["accounts"]}
    # alias → 계좌  (이체 '내용'에서 계좌를 찾기 위해)
    alias_to_acc: list[tuple[str, dict]] = []
    for a in prof["accounts"]:
        for al in a.get("aliases", []) or []:
            alias_to_acc.append((al, a))
    alias_to_acc.sort(key=lambda x: -len(x[0]))
    internal_kw = [k for k in prof["transfers"].get("internal_keywords", []) or []]
    family_rules = prof["transfers"].get("family", []) or []
    tol = int(prof["options"].get("small_transfer_ignore", 1000))

    def acc_of(t: Tx) -> dict:
        return accounts.get(t.account) or {"name": t.account, "kind": "?", "owner": "me", "role": "living", "_unknown": True}

    # ---- 이체 짝 찾기: 같은 |금액|, 반대 부호, ±1일, 다른 계좌
    transfers = [t for t in txs if t.type == "이체"]
    by_amt: dict[int, list[Tx]] = defaultdict(list)
    for t in transfers:
        by_amt[abs(t.amount)].append(t)
    pair: dict[int, Tx] = {}
    for amt, lst in by_amt.items():
        outs = [t for t in lst if t.amount < 0]
        ins = [t for t in lst if t.amount > 0]
        used = set()
        for o in outs:
            best = None
            for i in ins:
                if id(i) in used or i.account == o.account:
                    continue
                if abs((i.date - o.date).days) <= 1:
                    best = i
                    break
            if best:
                used.add(id(best))
                pair[id(o)] = best
                pair[id(best)] = o

    enrich = load_enrichment()
    suggestions = load_suggestions(min_conf=float(prof["options"].get("llm_min_confidence", 0.6)))
    suggested: dict[str, list[Tx]] = defaultdict(list)
    n_enrich = 0
    rows = []
    unresolved: dict[str, list[Tx]] = defaultdict(list)
    counts = defaultdict(int)

    for t in txs:
        a = acc_of(t)
        owner = a.get("owner", "me")
        role = a.get("role", "living")
        cat = sub = ""
        fixed = "N"
        status = reason = ""

        if (ov := overrides.get(tx_key(t))):
            cat, sub = ov.get("카테고리", ""), ov.get("세부", "")
            owner = ov.get("귀속") or owner
            fixed = ov.get("고정비") or "N"
            status, reason = "사용자", "overrides.csv"
            if cat == "제외":
                status = "제외"
            elif cat in INCOME_CATS:
                sub = sub or cat; cat = "수입"
            elif cat in CAPITAL_CATS:
                status = "자산거래"
            elif cat == "내부이체":
                status = "내부이체"
        elif role == "exclude":
            status, reason = "제외", f"계좌 role=exclude ({a['name']})"
            cat, sub = "제외", ""
        elif t.type == "이체":
            desc = t.desc
            hit_alias = next((acc for al, acc in alias_to_acc if al and al in desc), None)
            partner = pair.get(id(t))
            if t.bs_cat == "카드대금" or "카드대금" in desc or "카드출금" in desc:
                cat, sub, status, reason = "내부이체", "카드대금", "내부이체", "카드대금"
            elif partner is not None:
                pa = acc_of(partner)
                other = pa if t.amount < 0 else a
                if other.get("role") == "saving" and t.amount < 0:
                    cat, sub, status = "내부이체", "저축·투자 이체", "저축이체"
                elif a.get("role") == "saving" and t.amount > 0 and pa.get("role") != "saving":
                    cat, sub, status = "내부이체", "저축·투자 이체", "저축이체"
                else:
                    cat, sub, status = "내부이체", "계좌간이동", "내부이체"
                reason = f"짝: {partner.account} {partner.date}"
            elif hit_alias is not None:
                if hit_alias.get("role") == "saving":
                    cat, sub, status = "내부이체", "저축·투자 이체", "저축이체"
                    if t.amount > 0:
                        sub = "저축·투자 회수"
                else:
                    cat, sub, status = "내부이체", "계좌간이동", "내부이체"
                reason = f"alias '{hit_alias['name']}'"
            elif any(k and k in desc for k in internal_kw):
                cat, sub, status, reason = "내부이체", "계좌간이동", "내부이체", "internal_keywords"
            elif t.amount > 0 and (inc := next((r for r in prof["income"] if r.get("match") and r["match"] in desc and r.get("category")), None)):
                cat, sub = inc["category"], inc.get("sub", "")          # 급여가 '이체'로 들어오는 경우 (뱅샐이 종종 저축으로 오분류)
                status, reason = "수입원", f"income '{inc['match']}' (이체로 입금)"
            elif (rule := next((r for r in rules if r["키워드"] in desc), None)):
                cat, sub = rule["카테고리"], rule.get("세부", "")
                fixed = (rule.get("고정비") or "N").upper()[:1]
                owner = rule.get("귀속") or owner
                status, reason = "룰", f"rules '{rule['키워드']}' (이체)"
                if cat in INCOME_CATS:
                    sub = sub or cat; cat = "수입"
                elif cat in CAPITAL_CATS:
                    status = "자산거래"
                elif cat == "내부이체":
                    status = "내부이체"
            else:
                fam = next((r for r in family_rules if r.get("match") and r["match"] in desc), None)
                if fam:
                    cat, sub = fam.get("category", "가족"), fam.get("sub", "")
                    status, reason = "가족이전", f"family '{fam['match']}'"
                elif t.bs_cat in BS_CAT_MAP and t.bs_cat not in ("이체",):
                    cat, sub = BS_CAT_MAP[t.bs_cat]
                    status, reason = "뱅샐", f"뱅샐 {t.bs_cat}"
                else:
                    status, reason = "확인필요", "이체 상대 미상"
                    cat, sub = "확인필요", "이체"
        else:
            desc = t.desc
            rule = next((r for r in rules if r["키워드"] in desc), None)
            rec = next((r for r in prof["recurring"] if r.get("match") and r["match"] in desc and r.get("category")), None)
            inc = next((r for r in prof["income"] if r.get("match") and r["match"] in desc and r.get("category")), None) if t.type == "수입" else None
            if rule:
                cat, sub = rule["카테고리"], rule.get("세부", "")
                fixed = (rule.get("고정비") or "N").upper()[:1]
                owner = rule.get("귀속") or owner
                status, reason = "룰", f"rules '{rule['키워드']}'"
                if cat in INCOME_CATS:
                    sub = sub or cat; cat = "수입"
                elif cat in CAPITAL_CATS:
                    status = "자산거래"
                elif cat == "내부이체":
                    status = "내부이체"
            elif rec:
                cat, sub = rec["category"], rec.get("sub", "")
                fixed = "Y" if rec.get("fixed", True) else "N"
                status, reason = ("고정비" if fixed == "Y" else "룰"), f"recurring '{rec['match']}'"
            elif inc:
                cat, sub = inc["category"], inc.get("sub", "")
                status, reason = "수입원", f"income '{inc['match']}'"
            elif t.bs_cat in BS_CAT_MAP:
                cat, sub = BS_CAT_MAP[t.bs_cat]
                status, reason = "뱅샐", f"뱅샐 {t.bs_cat}"
            elif t.bs_cat != "미분류":
                cat = t.bs_cat
                sub = t.bs_sub if t.bs_sub != "미분류" else ""
                status, reason = "뱅샐", "뱅샐 자동분류"
            elif t.type == "수입":
                cat, sub, status, reason = "수입", "기타수입", "뱅샐", "수입 미분류"
            else:
                status, reason = "확인필요", "가맹점 미상"
                cat, sub = "확인필요", ""
            if sub in fixed_subs:
                fixed = "Y"
            if role == "business" and cat not in ("수입",):
                cat, sub = "사업", sub or cat
        # ---- 품목 보강: 쿠팡·네이버페이 주문과 금액·날짜로 맞춰 품목을 붙이고, 장터 거래는 품목으로 룰 재적용
        item = match_enrichment(t, enrich) if t.type != "이체" and status != "제외" else ""
        if item:
            n_enrich += 1
            is_market = status == "확인필요" or any(k in t.desc for k in MARKET_KW)
            if is_market and status != "사용자":
                r2 = next((r for r in rules if r["키워드"] in item), None)
                if r2:
                    cat, sub = r2["카테고리"], r2.get("세부", "")
                    fixed = (r2.get("고정비") or "N").upper()[:1]
                    if cat in INCOME_CATS:
                        sub = sub or cat; cat = "수입"
                    status, reason = "룰", f"rules(품목) '{r2['키워드']}'"
                    if status == "확인필요":
                        pass
                elif status == "확인필요":
                    reason = "가맹점 미상 (품목은 있음)"
        if status == "확인필요" and suggestions:
            gk = normalize_merchant(t.desc) + ("|이체" if t.type == "이체" else "")
            sg = suggestions.get(gk) or suggestions.get(normalize_merchant(t.desc))
            if sg:
                cat, sub = sg["카테고리"], sg.get("세부", "")
                if cat in INCOME_CATS:
                    sub = sub or cat; cat = "수입"
                fixed = (sg.get("고정비") or "N").upper()[:1]
                status = "추정"
                reason = f"AI 추정 {sg['_conf']:.2f} — {sg.get('근거', '')}"
                if cat in CAPITAL_CATS:
                    status = "자산거래"
                elif cat == "내부이체":
                    status = "내부이체"
                if status == "추정":
                    suggested[gk].append(t)
        if a.get("_unknown"):
            reason += " · 계좌 미등록(프로필에 추가 권장)"
            counts["계좌미등록"] += 1
        counts[status] += 1
        if status == "확인필요":
            unresolved[normalize_merchant(t.desc) + ("|이체" if t.type == "이체" else "")].append(t)
            if item:
                t.memo = item
        rows.append({
            "날짜": t.date.isoformat(), "시간": t.time, "월": t.month,
            "귀속": members.get(owner, {}).get("label", owner), "계좌": t.account, "계좌성격": role,
            "타입": t.type, "내용": t.desc, "품목": item, "금액": t.amount,
            "카테고리": cat, "세부": sub, "고정비": fixed, "상태": status, "근거": reason,
            "거래키": tx_key(t),
        })

    LEDGER.mkdir(parents=True, exist_ok=True)
    with open(LEDGER / "ledger.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
        w.writeheader()
        w.writerows(rows)

    # ---- 확인필요 보고
    total_unres = sum(abs(t.amount) for lst in unresolved.values() for t in lst)
    L = ["# 확인필요 목록\n", f"> build_ledger.py 생성. 묶음 {len(unresolved)}개 · {sum(len(v) for v in unresolved.values())}건 · {won(total_unres)}\n",
         "> 답은 가맹점 단위면 `private/rules.csv` 에 한 줄, 거래 한 건이면 `private/ledger/overrides.csv` 에 한 줄로 적고 다시 build.\n"]
    for k, lst in sorted(unresolved.items(), key=lambda kv: -sum(abs(t.amount) for t in kv[1])):
        s = sum(abs(t.amount) for t in lst)
        L.append(f"## {k}  —  {len(lst)}건 · {won(s)}")
        for t in lst[:6]:
            L.append(f"- {t.date} {t.account} `{t.desc}`{' — ' + t.memo[:60] if t.memo else ''} {won(t.amount)}  (뱅샐: {t.bs_cat}/{t.bs_sub})  키=`{tx_key(t)}`")
        if len(lst) > 6:
            L.append(f"- … 외 {len(lst)-6}건")
        L.append("")
    if suggested:
        L.insert(3, "")
        S = ["## AI 추정 (확인만 — 틀린 것만 고쳐주세요)\n",
             "> 신뢰도 0.6 이상만 적용됨. 맞으면 '맞아' → `suggest.py --promote` 로 룰에 승격. 틀리면 '번호 → 카테고리'.\n",
             "| 번호 | 묶음 | 건수 | 합계 | 추정 | 신뢰도 | 근거 |", "|---:|---|---:|---:|---|---:|---|"]
        for i, (k, lst) in enumerate(sorted(suggested.items(), key=lambda kv: -sum(abs(t.amount) for t in kv[1])), 1):
            sg = suggestions.get(k) or suggestions.get(k.split("|")[0])
            S.append(f"| {i} | {k} | {len(lst)} | {won(sum(abs(t.amount) for t in lst))} | {sg['카테고리']}/{sg.get('세부','')} | {sg['_conf']:.2f} | {sg.get('근거','')} |")
        S.append("")
        L[3:3] = S
    SETUP.mkdir(parents=True, exist_ok=True)
    (SETUP / "03_확인필요.md").write_text("\n".join(L), encoding="utf-8")

    if not (LEDGER / "overrides.csv").exists():
        (LEDGER / "overrides.csv").write_text("거래키,카테고리,세부,귀속,고정비,메모\n", encoding="utf-8-sig")

    n = len(rows)
    print(f"✔ ledger {n:,}건 → {LEDGER/'ledger.csv'}")
    for k in ("뱅샐", "룰", "고정비", "수입원", "내부이체", "저축이체", "자산거래", "가족이전", "사용자", "추정", "제외", "확인필요", "계좌미등록"):
        if counts[k]:
            print(f"   {k:6s} {counts[k]:5d}  ({counts[k]/n:.0%})")
    print(f"   품목 보강 {n_enrich}건 (쿠팡 {sum(1 for o in enrich['coupang'] if o['used'])}/{len(enrich['coupang'])} · 네이버 {sum(1 for o in enrich['naver'] if o['used'])}/{len(enrich['naver'])})")
    print(f"   확인필요 묶음 {len(unresolved)}개 → {SETUP/'03_확인필요.md'}" + (f"  (AI 추정 적용 {len(suggested)}묶음)" if suggested else "  → 다음: python3 scripts/suggest.py --prepare"))


if __name__ == "__main__":
    main(sys.argv)
