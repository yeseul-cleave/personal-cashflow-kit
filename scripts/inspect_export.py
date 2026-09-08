#!/usr/bin/env python3
"""0단계: export 진단 → 프로필 초안 + 인터뷰 질문지 생성.

사용:  python3 scripts/inspect_export.py [export.xlsx ...]
출력:  private/setup/01_진단.md
       private/setup/profile.draft.yaml   (→ 인터뷰 후 private/profile.yaml 로 저장)
       private/setup/02_질문지.md         (AI가 이 순서로 한 번에 하나씩 묻는다)

사람이 빈 양식을 채우는 게 아니라, 이 파일이 만든 '근거 있는 질문'에 답만 하면 된다.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from statistics import median

import yaml

from common import (SETUP, TEMPLATES, Tx, find_exports, guess_kind, load_rules, load_status, load_transactions,
                    normalize_merchant, won)

NAME_RE = re.compile(r"^[가-힣]{2,4}$")   # 사람 이름처럼 보이는 내용
GENERIC = {"주식회사", "(주)", "㈜", "유한회사", "결제", "이체", "송금", "입금", "출금", "카드", "페이", "간편결제", "자동이체", "이자", "수수료", "네이버", "토스", "카카오", "현대", "삼성", "신한", "국민", "우리", "하나", "농협"}
COMPANY_RE = re.compile(r"주식회사|\(주\)|㈜|유한회사|법인|Inc|Co\.")
BROKER_RE = re.compile(r"증권|투자증권|자산운용|업비트|빗썸|코인원|투자|CMA")   # 이체 상대가 증권·코인이면 저축·투자 계좌


def good_keyword(k: str) -> bool:
    """룰 키워드로 쓸 만한가: 너무 짧거나 일반 단어면 안 된다."""
    k = k.strip()
    return len(k) >= 3 and k not in GENERIC and not k.isdigit()


def main(argv: list[str]) -> None:
    files = find_exports(argv[1:] or None)
    txs: list[Tx] = []
    for f in files:
        txs += load_transactions(f)
    status = load_status(files[-1])
    SETUP.mkdir(parents=True, exist_ok=True)

    txs.sort(key=lambda t: (t.date, t.time))
    months = sorted({t.month for t in txs})
    by_type = Counter(t.type for t in txs)
    unclassified = [t for t in txs if t.type == "지출" and t.bs_cat == "미분류"]

    # ---- 계좌 목록 (결제수단 ∪ 현황 상품명)
    acc_stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "지출": 0, "수입": 0, "이체": 0, "months": set()})
    for t in txs:
        s = acc_stats[t.account]
        s["n"] += 1
        s[t.type] += abs(t.amount)
        s["months"].add(t.month)
    status_names = {a["name"]: a for a in status.assets} | {l["name"]: l for l in status.liabilities}
    acc_cats: dict[str, Counter] = defaultdict(Counter)       # 계좌별 지출 카테고리(뱅샐) 금액
    acc_income_cats: dict[str, Counter] = defaultdict(Counter)
    for t in txs:
        if t.type == "지출":
            acc_cats[t.account][t.bs_cat] += abs(t.amount)
        elif t.type == "수입":
            acc_income_cats[t.account][t.bs_cat] += abs(t.amount)

    # ---- 계좌 성격 추정: 외부 지식(상품명) + 거래 패턴. 사용자는 틀린 것만 고친다.
    KNOWN = [  # (이름에 포함, role, 설명)
        ("국민행복", "exclude", "정부 바우처 카드(보육료·임신 지원) — 국가 지원금 결제라 내 돈 아님. 본인 부담분만 있으면 '생활'로"),
        ("하이패스", "living", "통행료 전용 후불카드"),
        ("나눠모으기", "saving", "토스 목적별 저축 통장"),
        ("저금통", "saving", "잔돈 저축"),
        ("플러스박스", "saving", "케이뱅크 파킹통장"),
        ("세이프박스", "saving", "카카오뱅크 파킹통장"),
        ("모으기", "saving", "저축 통장"),
        ("청약", "saving", "주택청약"),
        ("적금", "saving", "적금"),
        ("자립예탁금", "living", "신협 입출금 계좌 (집단대출 실행 경로로 자주 쓰임)"),
        ("마이너스", "loan", "마이너스 통장"),
        ("CMA", "saving", "증권사 CMA"),
        ("연금", "saving", "연금 계좌"),
        ("IRP", "saving", "퇴직연금"),
    ]

    def infer_role(name: str, kind: str, st: dict) -> tuple[str, str]:
        for kw, role, why in KNOWN:
            if kw in name:
                return role, f"{why}"
        if kind in ("savings", "pension", "investment"):
            return "saving", "저축·투자 상품"
        if kind == "loan":
            return "loan", "대출"
        n, sp, inc, tr = st["n"], st["지출"], st["수입"], st["이체"]
        cats = acc_cats.get(name, Counter())
        top = cats.most_common(3)
        if kind == "checking":
            icats = acc_income_cats.get(name, Counter()).most_common(2)
            if inc >= 3_000_000:
                return "living", "수입이 들어오는 주거래 통장 (" + " · ".join(f"{c} {won(v)}" for c, v in icats) + f") · 이체 {won(tr)}"
            if tr >= 100_000_000:
                return "living", f"큰 이체 경유 ({won(tr)}) — 대출 실행·부동산·증권 입출금 경로로 추정. 성격은 '생활', 큰 이체는 자산거래로 분류"
            if n <= 5 and sp == 0 and inc == 0:
                return "living", "거의 안 쓰는 계좌 (휴면에 가까움)"
            if sp == 0:
                return "living", f"이체 위주 통장 (이체 {won(tr)})"
        if sp:
            share = top[0][1] / sp if top else 0
            desc = " · ".join(f"{c} {v/sp:.0%}" for c, v in top)
            if share >= 0.85 and top[0][0] not in ("미분류",):
                return "living", f"{top[0][0]} 전용 ({desc})"
            return "living", f"생활 결제 ({desc})"
        if kind in ("card", "pay") and sp == 0 and tr:
            return "living", "지출 없이 충전·이체만 — 충전형 머니(충전은 내부이체로 처리)"
        if kind == "checking":
            if inc >= 3_000_000 and inc >= tr * 0.05:
                icats = acc_income_cats.get(name, Counter()).most_common(2)
                return "living", "수입이 들어오는 주거래 통장 (" + " · ".join(f"{c} {won(v)}" for c, v in icats) + ")"
            if tr >= 100_000_000 and n <= 200:
                return "living", f"큰 이체 경유 ({won(tr)}) — 대출 실행·부동산·증권 입출금 경로로 추정 (성격은 '생활'로 두고 이체는 자산거래로 분류)"
            if n <= 5 and sp == 0 and inc == 0:
                return "living", "거의 안 쓰는 계좌 (휴면에 가까움)"
            return "living", f"이체 위주 통장 (이체 {won(tr)})"
        return "living", "패턴 특이점 없음"


    # ---- 반복 거래 후보 (같은 내용이 3개월 이상, 금액 편차 ±15%)
    grp: dict[tuple, list[Tx]] = defaultdict(list)
    for t in txs:
        if t.type == "이체" and t.amount < 0:
            continue                                  # 나가는 이체는 사람 송금 섹션에서 다룬다
        key = normalize_merchant(t.desc)
        if not good_keyword(key):
            key = t.desc.strip()[:14]                 # 일반 단어면 원문 앞부분을 키워드로
        grp[(key, t.account)].append(t)
    recurring = []
    for (m, acc), lst in grp.items():
        ms = {t.month for t in lst}
        if len(ms) < 3 or not good_keyword(m):
            continue
        amts = [abs(t.amount) for t in lst]
        med = median(amts)
        stable = sum(1 for a in amts if abs(a - med) <= max(med * 0.15, 1000))
        if stable >= 3:
            typ = lst[0].type
            if typ == "이체" and lst[0].amount > 0:
                typ = "수입(이체)"                     # 회사에서 매달 들어오는 이체 = 급여 후보
            recurring.append({"match": m, "account": acc, "months": len(ms), "median": int(med),
                              "type": typ, "bs_cat": Counter(t.bs_cat for t in lst).most_common(1)[0][0],
                              "sample": lst[-1].desc, "company": bool(COMPANY_RE.search(lst[-1].desc))})
    recurring.sort(key=lambda r: -r["median"] * r["months"])

    # ---- 공통 시드 룰 (templates/rules.csv) — 누구나 같은 브랜드는 묻지 않는다
    seed = load_rules(TEMPLATES / "rules.csv")
    def seed_hit(text: str):
        return next((r for r in seed if r["키워드"] in text), None)
    for r in recurring:
        h = seed_hit(r["sample"]) or seed_hit(r["match"])
        r["guess"] = f"{h['카테고리']}/{h['세부']}" if h else (r["bs_cat"] if r["bs_cat"] != "미분류" else "")
        r["guess_cat"] = h["카테고리"] if h else (r["bs_cat"] if r["bs_cat"] != "미분류" else "")
        r["guess_sub"] = h["세부"] if h else ""
        r["fixed"] = (h["고정비"].upper().startswith("Y") if h else False) or r["bs_cat"] in ("주거/통신", "육아", "교육", "보험", "구독")

    # ---- 미분류 가맹점 클러스터 (시드 룰로 잡히는 건 자동 → 질문 제외)
    clusters: dict[str, list[Tx]] = defaultdict(list)
    auto_by_seed = 0
    for t in unclassified:
        if seed_hit(t.desc):
            auto_by_seed += 1
            continue
        clusters[normalize_merchant(t.desc)].append(t)
    cl_sorted = sorted(clusters.items(), key=lambda kv: -sum(abs(t.amount) for t in kv[1]))
    total_unc = sum(abs(t.amount) for t in unclassified) or 1

    # ---- 이체 상대 (사람 이름 패턴 / 계좌명 아닌 것)
    transfer_desc = Counter()
    transfer_amt = Counter()
    for t in txs:
        if t.type == "이체":
            k = normalize_merchant(t.desc)
            transfer_desc[k] += 1
            transfer_amt[k] += abs(t.amount)
    account_words = set()
    for a in acc_stats:
        account_words.update(a.replace("(", " ").replace(")", " ").split())
    people_like = [(k, n, transfer_amt[k]) for k, n in transfer_desc.most_common()
                   if NAME_RE.match(k) or (k not in account_words and n >= 3)]

    # ---- 수입 내용
    income_desc = Counter()
    income_amt = Counter()
    for t in txs:
        if t.type == "수입":
            k = normalize_merchant(t.desc)
            income_desc[k] += 1
            income_amt[k] += t.amount
    incomes = sorted(income_desc.items(), key=lambda kv: -income_amt[kv[0]])

    # ================================================================ 01_진단.md
    L = []
    L.append(f"# export 진단\n")
    L.append(f"> 원본: {', '.join(f.name for f in files)}  ·  생성: 자동 (inspect_export.py)\n")
    L.append(f"- 기간: **{months[0]} ~ {months[-1]}** ({len(months)}개월), 거래 **{len(txs):,}건**")
    L.append(f"- 타입: 지출 {by_type['지출']:,} · 수입 {by_type['수입']:,} · 이체 {by_type['이체']:,}")
    L.append(f"- 지출 중 뱅샐 미분류: **{len(unclassified):,}건 / {won(total_unc)}** — 그중 공통 룰로 자동 {auto_by_seed}건, 인터뷰로 채울 몫 {len(unclassified)-auto_by_seed}건")
    if status.person:
        L.append(f"- 현황 시트: {status.person.get('이름','?')} · 자산 {len(status.assets)}건 · 부채 {len(status.liabilities)}건 · 투자 {len(status.investments)}건 · 대출 {len(status.loans)}건 · 보험 {len(status.insurance)}건")
    L.append("")
    L.append("## 결제수단 (거래에 나온 계좌·카드)\n")
    L.append("| 결제수단 | 추정종류 | 건수 | 지출 | 수입 | 이체 | 활동월 |")
    L.append("|---|---|---:|---:|---:|---:|---:|")
    for a, s in sorted(acc_stats.items(), key=lambda kv: -kv[1]["n"]):
        L.append(f"| {a} | {guess_kind(a)} | {s['n']} | {won(s['지출'])} | {won(s['수입'])} | {won(s['이체'])} | {len(s['months'])} |")
    L.append("")
    if status.assets or status.liabilities:
        L.append("## 현황 시트의 자산·부채 (export 시점)\n")
        L.append("| 구분 | 그룹 | 상품명 | 금액 |")
        L.append("|---|---|---|---:|")
        for a in status.assets:
            if a["value"]:
                L.append(f"| 자산 | {a['group']} | {a['name']} | {won(a['value'])} |")
        for l in status.liabilities:
            if l["value"]:
                L.append(f"| 부채 | {l['group']} | {l['name']} | {won(l['value'])} |")
        L.append("")
    if status.loans:
        L.append("## 대출\n")
        L.append("| 금융사 | 상품 | 원금 | 잔액 | 금리 | 만기 |")
        L.append("|---|---|---:|---:|---:|---|")
        for l in status.loans:
            L.append(f"| {l['금융사']} | {l['상품명']} | {won(l['대출원금'])} | {won(l['대출잔액'])} | {l['대출금리']}% | {str(l['대출만기일'])[:10]} |")
        L.append("")
    L.append("## 반복 거래 후보 (3개월 이상, 금액 안정)\n")
    L.append("| 내용 | 계좌 | 개월 | 중앙값 | 뱅샐분류 |")
    L.append("|---|---|---:|---:|---|")
    for r in recurring[:40]:
        L.append(f"| {r['match']} | {r['account']} | {r['months']} | {won(r['median'])} | {r['bs_cat']} |")
    L.append("")
    L.append("## 미분류 지출 상위 가맹점 (금액순)\n")
    L.append("| 가맹점(묶음) | 건수 | 합계 | 비중 | 예시 |")
    L.append("|---|---:|---:|---:|---|")
    cum = 0
    for m, lst in cl_sorted[:60]:
        s = sum(abs(t.amount) for t in lst)
        cum += s
        L.append(f"| {m} | {len(lst)} | {won(s)} | {s/total_unc:.0%} | {lst[-1].desc} ({lst[-1].account}) |")
    L.append(f"\n상위 60개 묶음이 미분류 금액의 **{cum/total_unc:.0%}** 를 차지한다.\n")
    L.append("## 이체 상대 (사람·미상)\n")
    L.append("| 내용 | 건수 | 합계 |")
    L.append("|---|---:|---:|")
    for k, n, a in people_like[:30]:
        L.append(f"| {k} | {n} | {won(a)} |")
    L.append("")
    L.append("## 수입 내용\n")
    L.append("| 내용 | 건수 | 합계 |")
    L.append("|---|---:|---:|")
    for k, n in incomes[:20]:
        L.append(f"| {k} | {n} | {won(income_amt[k])} |")
    L.append("")
    if status.cashflow_bs:
        L.append("## 뱅샐 자체 월별 집계 (교차검증용)\n")
        mos = sorted({m for v in status.cashflow_bs.values() for m in v})
        L.append("| 항목 | " + " | ".join(mos) + " |")
        L.append("|---|" + "---:|" * len(mos))
        for k, v in status.cashflow_bs.items():
            L.append(f"| {k} | " + " | ".join(f"{v.get(m, 0):,}" for m in mos) + " |")
        L.append("")
    (SETUP / "01_진단.md").write_text("\n".join(L), encoding="utf-8")

    # ================================================================ profile.draft.yaml
    accounts = []
    seen = set()
    for a, s in sorted(acc_stats.items(), key=lambda kv: -kv[1]["n"]):
        k = guess_kind(a)
        role, why = infer_role(a, k, s)
        accounts.append({"name": a, "kind": k, "owner": "me", "role": role, "_why": why,
                         "_hint": f"거래 {s['n']}건 · 지출 {won(s['지출'])} · 수입 {won(s['수입'])} · 이체 {won(s['이체'])}"})
        seen.add(a)
    for a in status.assets + status.liabilities:
        if a["name"] in seen or not a["value"]:
            continue
        k = guess_kind(a["name"]) if a["group"] is None else {
            "자유입출금 자산": "checking", "저축성 자산": "savings", "전자금융 자산": "pay",
            "투자성 자산": "investment", "연금 자산": "pension", "보험 자산": "insurance",
            "현금 자산": "cash", "장기대출": "loan", "단기대출": "loan"}.get(a["group"], guess_kind(a["name"]))
        role, why = infer_role(a["name"], k, {"n": 0, "지출": 0, "수입": 0, "이체": 0})
        if k == "loan":
            role, why = "loan", "대출"
        accounts.append({"name": a["name"], "kind": k, "owner": "me", "role": role, "_why": why,
                         "_hint": f"현황 {a['group']} · {won(a['value'])} (거래 없음, 잔액만)"})
        seen.add(a["name"])
    self_name = status.person.get("이름", "") if status.person else ""
    def is_self(k: str) -> bool:
        return bool(self_name) and (self_name in k or self_name.replace(self_name[1], "*") in k)
    broker_partners = sorted({normalize_merchant(t.desc) for t in txs if t.type == "이체" and BROKER_RE.search(t.desc) and good_keyword(normalize_merchant(t.desc))})
    for bp in broker_partners:
        if bp not in seen:
            accounts.append({"name": bp, "kind": "investment", "owner": "me", "role": "saving", "aliases": [bp],
                             "_why": "이체 상대가 증권·코인사 — 저축·투자 계좌로 추정 (export 에 계좌 없음, 이체만 보임)",
                             "_hint": f"이체 alias · {sum(1 for t in txs if bp in t.desc)}건"})
            seen.add(bp)
    salary_like = [r for r in recurring if r["type"] == "수입(이체)" and not is_self(r["match"]) and not BROKER_RE.search(r["match"])
                   and r["median"] >= 100_000 and r["match"] not in r["account"]]   # 이자·잔돈·자기 계좌명은 제외
    draft = {
        "version": 1,
        "household": {"label": status.person.get("이름", "나") if status.person else "나",
                      "members": [{"id": "me", "label": "나", "role": "self"}]},
        "accounts": accounts,
        "transfers": {"internal_keywords": [status.person["이름"]] if status.person.get("이름") else [],
                      "family": []},
        "recurring": [{"match": r["match"], "category": r.get("guess_cat", ""), "sub": r.get("guess_sub", ""),
                       "fixed": bool(r.get("fixed")),
                       "_hint": f"{r['months']}개월 · 중앙값 {won(r['median'])} · {r['account']} · {'고정' if r.get('fixed') else '변동'}"}
                      for r in recurring if r["type"] == "지출"][:40],
        "income": [{"match": k, "category": "수입", "sub": "", "_hint": f"{n}건 · {won(income_amt[k])}"}
                   for k, n in incomes[:10] if good_keyword(k)]
                  + [{"match": r["match"], "category": "수입", "sub": "급여" if r["company"] else "정기입금",
                      "_hint": f"이체로 매달 입금 · {r['months']}개월 · 중앙값 {won(r['median'])} · {r['account']}"}
                     for r in salary_like][:5],
        "options": {"business_split": False, "small_transfer_ignore": 1000},
    }
    with open(SETUP / "profile.draft.yaml", "w", encoding="utf-8") as f:
        f.write("# inspect_export.py 가 만든 초안. `_hint` 는 근거 메모이며 지워도 된다.\n")
        f.write("# 인터뷰가 끝나면 private/profile.yaml 로 저장한다. 양식 설명은 templates/profile.yaml.\n")
        yaml.safe_dump(draft, f, allow_unicode=True, sort_keys=False, width=120)

    # ================================================================ 02_질문지.md
    Q = []
    Q.append("# 인터뷰 질문지\n")
    Q.append("> 깔때기 순서: 가구 → 계좌 성격(추정 확인) → **매달 고정으로 나가는 것** → 사람 송금 → 남은 큰 미분류 → 수입 → 뱅샐에 없는 자산. 뱅샐이 이미 분류한 식사·카페·교통과 공통 룰로 잡히는 가맹점은 **묻지 않는다**.")
    Q.append("> AI는 이 순서로 **한 번에 하나씩** 묻고, 답을 profile.yaml / rules.csv 에 바로 적는다.")
    Q.append("> 질문에 붙은 표·목록은 **요약하지 않고 그대로** 보여준다. 행을 합치거나 '외 N개'로 줄이지 않는다.")
    Q.append("> 각 질문에는 근거(어디서 얼마가 움직였는지)가 붙어 있어 기억을 더듬지 않아도 된다.\n")
    n = 0
    KIND_LABEL = {"card": "카드", "checking": "통장", "pay": "간편결제", "savings": "청약·저축", "investment": "주식·ETF·펀드", "pension": "연금", "loan": "대출", "insurance": "보험", "cash": "현금", "?": "기타"}
    KIND_ORDER = ["card", "checking", "pay", "savings", "investment", "pension", "loan", "insurance", "cash", "?"]
    Q.append("## A. 가구 구성 (1문)\n")
    n += 1; Q.append(f"{n}. 이 가계부는 **혼자** 기준인가요, **가족(배우자·아이·부모님)** 과 같이 보나요? 같이 본다면 누구까지 한 지갑으로 볼까요?")
    if people_like:
        Q.append("   참고로 돈이 자주 오간 사람: " + ", ".join(f"{k}({cnt}건·{won(amt)})" for k, cnt, amt in people_like[:6]))
    Q.append("   (남의 돈이 섞인 계좌·카드는 다음 B에서 표를 보며 고른다.)")
    Q.append("")
    Q.append("## B. 계좌·카드 귀속\n")
    tx_accs = [a for a in accounts if not a["_hint"].startswith("현황")]
    st_accs = [a for a in accounts if a["_hint"].startswith("현황")]
    ROLE_KO = {"living": "생활", "saving": "저축·투자", "business": "사업", "custodial": "위탁", "exclude": "제외", "loan": "대출"}
    n += 1
    Q.append(f"{n}. 거래 패턴과 상품명으로 **계좌 성격을 추정**했습니다. 표를 보고 **틀린 것만** '번호 → 성격'으로 고쳐주세요. 성격은 생활 / 저축·투자 / 사업 / **위탁(남의 돈 섞임, 비율도)** / 제외(부모님 카드 등 남의 것). 예: '15 생활', '3 사업', '31 위탁 엄마 40%'. 다 맞으면 '맞아'.\n")
    Q.append("> AI에게: 아래 표를 줄이지 말고 그대로 보여줄 것.\n")
    for kind in KIND_ORDER:
        rows_k = [(accounts.index(a) + 1, a) for a in tx_accs if a["kind"] == kind]
        if not rows_k:
            continue
        Q.append(f"**{KIND_LABEL.get(kind, kind)}** ({len(rows_k)}개)\n")
        Q.append("| 번호 | 이름 | 추정 | 근거 |"); Q.append("|---:|---|---|---|")
        for i, a in rows_k:
            Q.append(f"| {i} | {a['name']} | **{ROLE_KO.get(a['role'], a['role'])}** | {a['_why']} |")
        Q.append("")
    if st_accs:
        n += 1
        Q.append(f"{n}. 잔액만 있는 자산 {len(st_accs)}개는 **전부 저축·투자(내 것)** 로 추정했습니다. 남의 돈이 섞였거나(위탁) 제외할 것만 번호로. 다 맞으면 '맞아'.\n")
        Q.append("| 종류 | 개수 | 번호 | 합계 | 항목 |"); Q.append("|---|---:|---|---:|---|")
        from collections import defaultdict as _dd
        grp = _dd(list)
        for a in st_accs:
            grp[a["kind"]].append(a)
        for k, v in grp.items():
            nums = [accounts.index(a) + 1 for a in v]
            total = 0
            for a in v:
                try: total += int(a["_hint"].split("·")[1].strip().split(" ")[0].replace(",", "").replace("원", ""))
                except (IndexError, ValueError): pass
            rng = f"{min(nums)}~{max(nums)}" if len(nums) > 1 else str(nums[0])
            Q.append(f"| {KIND_LABEL.get(k, k)} | {len(v)} | {rng} | {won(total)} | " + ", ".join(a['name'] for a in v) + " |")
        Q.append("")
    Q.append("")
    Q.append("## C. 매달 고정으로 나가는 것 (표 1개, 틀린 것만)\n")
    rec_exp = [r for r in recurring if r["type"] == "지출"]
    n += 1
    Q.append(f"{n}. 3개월 이상 비슷한 금액이 반복된 지출입니다. **추정 카테고리와 고정비 여부**를 보고 틀린 것만 '번호 → 카테고리' 또는 '번호 변동'으로 고쳐주세요. 다 맞으면 '맞아'.\n")
    Q.append("> AI에게: 표를 줄이지 말고 그대로. 고정비=매달 거의 같은 금액이 나가는 계약(월세·관리비·보험·구독·학원·보육료). 외식·쇼핑처럼 금액이 변하는 건 변동.\n")
    Q.append("| 번호 | 내용 | 개월 | 월 금액 | 계좌 | 추정 카테고리 | 고정? |"); Q.append("|---:|---|---:|---:|---|---|:---:|")
    for i, r in enumerate(rec_exp[:25], 1):
        Q.append(f"| {i} | {r['match']} | {r['months']} | {won(r['median'])} | {r['account']} | {r['guess'] or '?'} | {'고정' if r['fixed'] else '변동'} |")
    fixed_sum = sum(r["median"] for r in rec_exp[:25] if r["fixed"])
    Q.append(f"\n추정 고정비 합계 **월 {won(fixed_sum)}**. 여기서 확정된 것은 이후 달에 자동으로 고정비로 잡힌다.\n")
    Q.append("## D. 사람에게 간 이체 (상대당 1문)\n")
    for k, cnt, amt in people_like[:12]:
        n += 1
        Q.append(f"{n}. **{k}** 에게/에게서 {cnt}건 · {won(amt)} — 누구이고, 이 돈은 무엇인가요? (내 계좌 / 가족 이전 / 월세·보증금 / 빌려준 돈 / 모임비 …)")
    Q.append("")
    Q.append(f"## E. 남은 미분류 가맹점 (공통 룰로 {auto_by_seed}건 자동 처리 후, 금액 누적 80%까지)\n")
    acc_amt = 0
    for m, lst in cl_sorted:
        s = sum(abs(t.amount) for t in lst)
        if acc_amt >= total_unc * 0.8 and n > 0:
            break
        acc_amt += s
        n += 1
        Q.append(f"{n}. **{m}** — {len(lst)}건 · {won(s)} (예: {lst[-1].desc}) → 카테고리는?")
    Q.append("")
    Q.append("## F. 수입원\n")
    for r in salary_like[:5]:
        n += 1
        if r["company"]:
            Q.append(f"{n}. **{r['match']}** — 이체로 매달 입금, {r['months']}개월 · 약 {won(r['median'])} ({r['account']}) → **급여**로 볼게요. 아니면 뭔가요? (사업 / 배당 / 가족 지원 / 월세 수입)")
        else:
            Q.append(f"{n}. **{r['match']}** — 이체로 매달 입금, {r['months']}개월 · 약 {won(r['median'])} ({r['account']}) → 무엇인가요? (급여 / 사업 / 가족 지원 / 월세 수입 / 내 계좌 이동)")
    for k, cnt in incomes[:6]:
        if not good_keyword(k):
            continue
        n += 1
        Q.append(f"{n}. **{k}** — {cnt}건 · {won(income_amt[k])} → 급여 / 사업 / 배당·이자 / 가족 지원 / 환급 중?")
    Q.append("")
    Q.append("## G. 뱅샐에 없는 자산·부채 (1문)\n")
    n += 1
    Q.append(f"{n}. 부동산, 비상장주식, 전세보증금, 빌려준 돈, 개인적으로 빌린 돈이 있나요? 대략 금액이면 됩니다. (없으면 '없음')")
    Q.append(f"\n---\n총 {n}문. 계좌(B)와 이체 상대(C)가 핵심이고 D~F는 '맞아/아니' 수준. 확인형 질문은 답이 '네'면 다음으로.")
    (SETUP / "02_질문지.md").write_text("\n".join(Q), encoding="utf-8")

    print(f"✔ {len(txs):,}건 · {months[0]}~{months[-1]} · 계좌 {len(accounts)}개 · 미분류 {len(unclassified)}건 → 묶음 {len(clusters)}개")
    print(f"  {SETUP/'01_진단.md'}\n  {SETUP/'profile.draft.yaml'}\n  {SETUP/'02_질문지.md'}  ({n}문)")


if __name__ == "__main__":
    main(sys.argv)
