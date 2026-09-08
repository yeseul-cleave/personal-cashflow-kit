#!/usr/bin/env python3
"""3단계: '깨달음' — 투자 기초 프레임(재무제표 · 체크리스트 · 코어-새틀라이트)으로 내 숫자를 판정한다.

  python3 scripts/insight.py
출력: private/out/insight.md                       사람이 읽는 판정 (financial_profile.md 뒤에도 붙는다)
      private/out/투자기초_재무제표_자동.xlsx        템플릿의 회색 셀을 내 숫자로 채운 것 (만원 단위)
입력: private/out/cashflow_monthly.csv · balance_sheet.json · ledger.csv · profile.yaml · templates/investment_baseline.yaml
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from collections import defaultdict
from statistics import mean

import yaml

from common import LEDGER, OUT, PRIVATE, ROOT, TEMPLATES, find_exports, load_profile, load_status, won

MANWON = 10_000


def m(v) -> int:
    return int(round(float(v or 0) / MANWON))


def main() -> None:
    prof = load_profile()
    fw = yaml.safe_load(open(TEMPLATES / "investment_baseline.yaml", encoding="utf-8"))
    ck, cs = fw["checklist"], fw["core_satellite"]
    bs = json.load(open(OUT / "balance_sheet.json", encoding="utf-8"))
    iv = bs["investor"]
    recent = iv["baseline_months"]
    rows = [r for r in csv.DictReader(open(LEDGER / "ledger.csv", encoding="utf-8-sig", newline=""))]
    hh = {mm["label"] for mm in prof["household"]["members"] if mm.get("role") == "self" or mm.get("shared_household")}
    R = [r for r in rows if r["월"] in recent and r["귀속"] in hh and r["상태"] not in ("제외", "확인필요")]
    n = max(len(recent), 1)
    accounts = {a["name"]: a for a in prof["accounts"]}

    def avg(pred) -> float:
        return sum(-int(r["금액"]) for r in R if pred(r)) / n

    # ---------- ① 월 현금흐름 → 투자 기초 항목 매핑
    inc = lambda r: r["카테고리"] == "수입"
    salary = -avg(lambda r: inc(r) and r["세부"] in ("급여",))
    side = -avg(lambda r: inc(r) and r["세부"] in ("사업소득", "프리랜서", "기타수입", "정기입금", "용돈", "가족 지원", "환급"))
    fin = -avg(lambda r: inc(r) and r["세부"] in ("배당", "이자", "이자·배당", "배당·이자"))
    income_total = -avg(inc)
    other_inc = income_total - salary - side - fin
    side += max(other_inc, 0)
    exp = lambda r: r["카테고리"] not in ("수입", "내부이체", "자산거래", "제외") and r["상태"] not in ("내부이체", "저축이체", "자산거래")
    fixed = lambda r: exp(r) and r["고정비"] == "Y"
    debt = avg(lambda r: exp(r) and (r["세부"] in ("대출상환", "대출이자") or "대출" in r["세부"]))
    insur = avg(lambda r: exp(r) and (r["카테고리"] == "보험" or "보험" in r["카테고리"] or "보험" in r["세부"]))
    telecom = avg(lambda r: exp(r) and (r["세부"] in ("통신비", "인터넷") or "통신" in r["세부"]))
    housing = avg(lambda r: exp(r) and r["카테고리"] in ("주거/통신",) and r["세부"] not in ("통신비", "인터넷"))
    transport = avg(lambda r: exp(r) and r["카테고리"] in ("교통", "자동차", "교통/차량"))
    fixed_total = avg(fixed)
    other_fixed = max(fixed_total - sum(x for x in (debt, insur, telecom, housing, transport) if x > 0), 0)
    # 변동
    var_total = avg(lambda r: exp(r) and r["고정비"] != "Y")
    selfdev = avg(lambda r: exp(r) and r["고정비"] != "Y" and r["카테고리"] in ("교육",))
    other_var = avg(lambda r: exp(r) and r["고정비"] != "Y" and r["카테고리"] in ("경조사", "의료/건강", "여행/숙박", "세금/수수료", "가족", "경조사/가족행사"))
    living = max(var_total - selfdev - other_var, 0)
    # 저축·투자 (저축이체, 나가는 것 − 회수) — 상대 계좌 종류로 분배
    sav = defaultdict(float)
    for r in R:
        if r["상태"] != "저축이체":
            continue
        amt = -int(r["금액"]) / n
        kind = "investment"
        for name, a in accounts.items():
            if name and (name in r["근거"] or name in r["내용"]):
                kind = a.get("kind", "investment"); break
        sav[kind] += amt
    saving_dep = max(sav.get("savings", 0), 0)
    pension_acc = max(sav.get("pension", 0), 0)
    invest = max(sum(v for k, v in sav.items() if k not in ("savings", "pension")), 0)
    pension_ins = avg(lambda r: exp(r) and r["세부"] in ("저축성", "연금보험"))
    save_total = saving_dep + pension_acc + invest + pension_ins
    unres = mean([float(x["확인필요금액"]) for x in csv.DictReader(open(OUT / "cashflow_monthly.csv", encoding="utf-8-sig")) if x["월"] in recent]) if recent else 0
    gap = income_total - fixed_total - var_total - save_total       # 수지 차액 = 미파악 지출

    # ---------- ② 자산부채 → 투자 기초 항목
    A = bs["assets"]
    status = load_status(find_exports()[-1])
    inv_by_type = defaultdict(float)
    for i in status.investments:
        inv_by_type[str(i.get("투자상품종류") or "기타")] += float(i.get("평가금액") or 0)
    checking = A.get("checking", 0) + A.get("pay", 0) + A.get("cash", 0)
    subscription = sum(a["value"] for a in status.assets if a["value"] and "청약" in a["name"])
    emergency = sum(a["value"] for a in status.assets if a["value"] and any(k in a["name"] for k in ("비상", "나눠모으기", "파킹", "CMA", "세이프박스", "플러스박스")))
    savings_other = max(A.get("savings", 0) - subscription - emergency, 0)
    stocks = inv_by_type.get("주식", 0)
    funds = inv_by_type.get("펀드", 0)
    bonds = inv_by_type.get("채권", 0)
    inv_total = A.get("investment", 0)
    inv_other = max(inv_total - stocks - funds - bonds, 0)
    pension = A.get("pension", 0)
    realestate = A.get("realestate", 0)
    unlisted = A.get("unlisted", 0)
    liab_fin = sum(v for k, v in bs["liabilities"].items() if "대출" in k or k in ("부채",))
    liab_other = bs["total_liabilities"] - liab_fin
    total_assets, net = bs["total_assets"], bs["net_worth"]
    seed = checking + subscription + emergency + savings_other + inv_total + unlisted
    savings_rate = (save_total / income_total) if income_total else 0
    debt_ratio = (bs["total_liabilities"] / total_assets) if total_assets else 0

    # ---------- ②-b 구독·편의식비·늘어난 것 (거울용)
    SUBS_avg = avg(lambda r: exp(r) and (r["카테고리"] == "구독" or r["세부"] in ("OTT", "소프트웨어", "멤버십")))
    conv = avg(lambda r: exp(r) and (r["카테고리"] in ("식사", "카페/간식") or r["세부"] in ("배달", "외식", "카페", "편의점", "디저트")))
    all_months = sorted({r["월"] for r in rows})
    prev = [mm for mm in all_months if mm < recent[0]][-len(recent):] if recent else []
    ups_txt = ""
    if prev:
        def cat_avg(months):
            d = defaultdict(float)
            for r in rows:
                if r["월"] in months and r["귀속"] in hh and r["상태"] not in ("제외", "확인필요") and exp(r) and int(r["금액"]) < 0:
                    d[r["카테고리"]] += -int(r["금액"]) / len(months)
            return d
        ca, pa = cat_avg(recent), cat_avg(prev)
        ups = sorted(((c, ca[c] - pa.get(c, 0)) for c in ca if ca[c] - pa.get(c, 0) > 50_000), key=lambda x: -x[1])[:3]
        ups_txt = ", ".join(f"{c} +{won(d)}/월" for c, d in ups)

    # ---------- ③ 코어-새틀라이트: 보유 종목 분류
    cl = fw["classify"]
    def bucket(name: str) -> str:
        nm = name.lower()
        if any(k.lower() in nm for k in cl["safe"]): return "안전자산"
        if any(k.lower() in nm for k in cl["core"]): return "코어"
        if any(k.lower() in nm for k in cl["dividend"]): return "위성(배당·팩터)"
        return "위성(개별주·섹터)"
    port = defaultdict(float)
    for i in status.investments:
        port[bucket(str(i.get("상품명") or ""))] += float(i.get("평가금액") or 0)
    port_total = sum(port.values()) or 1
    core_share = port["코어"] / port_total

    # ---------- ④ xlsx 채우기
    tpl = TEMPLATES / "external" / "financial_statement_template.xlsx"
    xlsx_out = None
    if tpl.exists():
        import openpyxl
        xlsx_out = OUT / "투자기초_재무제표_자동.xlsx"
        shutil.copy(tpl, xlsx_out)
        wb = openpyxl.load_workbook(xlsx_out)
        cf, ab = wb["월 현금흐름"], wb["자산부채 현황"]
        for cell, v in {"C6": salary, "C7": side, "C8": fin, "C13": debt, "C14": insur, "C15": telecom, "C16": housing, "C17": transport, "C18": other_fixed,
                        "C23": living, "C24": selfdev, "C25": other_var, "C30": saving_dep, "C31": pension_ins, "C32": pension_acc, "C33": invest}.items():
            cf[cell] = m(v)
        for cell, v in {"C6": savings_other, "C7": checking, "C8": subscription, "C9": emergency, "C14": 0, "C15": stocks, "C16": funds, "C17": bonds, "C18": inv_other + unlisted,
                        "C23": 0, "C24": pension, "C29": realestate, "C34": liab_fin, "C35": liab_other}.items():
            ab[cell] = m(v)
        cf["D2"] = f"킷 자동 채움 · 최근 {len(recent)}개월 평균 · 확인필요 월 {m(unres)}만원 미포함"
        wb.save(xlsx_out)

    # ---------- ⑤ 관찰: 투자 성향 (판정 아님, 데이터에서 보이는 것)
    buy_months = {r["월"] for r in rows if r["상태"] == "저축이체" and int(r["금액"]) < 0 and r["월"] in recent}
    inv_share = (inv_total / total_assets) if total_assets else 0
    active = inv_share >= 0.3 or len(buy_months) >= 2
    idle_cash = checking + emergency + savings_other
    idle_months = (idle_cash / var_total) if var_total else 0
    sat_share = (port["위성(개별주·섹터)"] / port_total) if port_total > 1 else 0

    # ---------- ⑥ "집" 시나리오
    opt = prof.get("options", {}) or {}
    home_price = float(opt.get("home_goal_price", 500_000_000) or 0)
    ltv = float(opt.get("home_ltv", 0.7)); extra = float(opt.get("home_extra_cost", 0.02))
    need_cash = home_price * (1 - ltv + extra) if home_price else 0
    deposit = A.get("deposit", 0)                       # 전세보증금 (manual_assets kind: deposit)
    have = seed + deposit                                # 종잣돈 + 보증금
    rr = float(opt.get("return_rate", 0.04))
    monthly_net = max(iv["monthly_net_cashflow"], 0)     # 실제로 남는 돈 (저축이체 포함 전)

    def years_to(target: float, start: float, monthly: float, r: float = rr) -> float | None:
        if start >= target: return 0.0
        if monthly <= 0 and r <= 0: return None
        bal, yrs = start, 0.0
        while bal < target and yrs < 60:
            bal = bal * (1 + r / 12) + monthly; yrs += 1 / 12
        return None if yrs >= 60 else yrs
    def fv(start: float, monthly: float, years: int, r: float = rr) -> float:
        return start * (1 + r) ** years + monthly * 12 * (((1 + r) ** years - 1) / r if r else years)
    def y(v): return "도달 못함 (60년+)" if v is None else ("지금" if v == 0 else f"{v:.1f}년")

    scen = [("지금 페이스", monthly_net), ("월 +30만", monthly_net + 300_000), ("월 +50만", monthly_net + 500_000), ("월 +100만", monthly_net + 1_000_000)]
    conv_cut = conv * 0.5 if 'conv' in dir() else 0

    # ---------- ⑦ insight.md (거울)
    L = ["# 지금 페이스면 — 내 숫자가 말하는 것", f"> 최근 {len(recent)}개월({recent[0] if recent else '-'}~{recent[-1] if recent else '-'}) 평균 · 판정이 아니라 관찰 · 숫자는 전부 내 거래에서 나옴", ""]
    L.append("## 1. 한 달에 실제로 남는 돈")
    L.append(f"- 들어오는 돈 **{won(income_total)}** → 나가는 돈 **{won(fixed_total + var_total)}** (고정 {won(fixed_total)} + 변동 {won(var_total)}) → 남는 돈 **{won(monthly_net)}**")
    L.append(f"- 그중 이미 저축·투자 계좌로 가는 돈 {won(save_total)}. 나머지 {won(max(monthly_net - save_total, 0))} 는 통장에 그냥 쌓이거나 다음 달에 쓰인다.")
    if unres > income_total * 0.05:
        L.append(f"- 아직 정체를 못 정한 돈이 월 {won(unres)} 있다. 이건 위 숫자에 안 들어 있다.")
    L.append(f"- 손 안 대고 자동으로 나가는 돈: 구독·멤버십 월 {won(SUBS_avg)} (연 {won(SUBS_avg*12)})" if SUBS_avg else "")
    L.append("")
    L.append("## 2. 지금 가진 것")
    L.append(f"- 바로 쓸 수 있는 돈 {won(idle_cash)} (변동지출 {idle_months:.1f}개월치), 투자자산 {won(inv_total)}, 연금 {won(pension)}" + (f", 전세보증금 {won(deposit)}" if deposit else "") + (f", 부채 {won(bs['total_liabilities'])}" if bs['total_liabilities'] else ""))
    L.append(f"- 순자산 **{won(net)}**. 집·연금 빼고 움직일 수 있는 돈(종잣돈) **{won(seed)}**")
    L.append("")
    L.append("## 3. 이 페이스로 가면")
    L.append("| | 1년 뒤 | 5년 뒤 | 10년 뒤 |"); L.append("|---|---:|---:|---:|")
    for name, mo in scen[:3]:
        L.append(f"| {name} ({won(mo)}/월) | {won(fv(seed, mo, 1))} | {won(fv(seed, mo, 5))} | {won(fv(seed, mo, 10))} |")
    L.append(f"\n(종잣돈 {won(seed)} 에서 시작, 연 {rr:.0%} 가정. 저축률로 말하면 지금 {savings_rate:.0%}.)\n")
    has_home = realestate > 0 or any(("주택" in k or "집단" in k or "담보" in k) for k in bs["liabilities"]) or any(("주택" in str(l.get("name", "")) or "집단" in str(l.get("name", ""))) for l in bs.get("loans", []))
    mort_rate = float(opt.get("home_loan_rate", 0.04)); mort_years = int(opt.get("home_loan_years", 30))
    def annuity(principal: float, r: float, years: int) -> float:
        n_ = years * 12; i = r / 12
        return principal * i / (1 - (1 + i) ** -n_) if i else principal / n_
    if home_price and not has_home:
        L.append(f"## 4. 집 — {won(home_price)} 짜리를 산다면")
        L.append(f"- 대출 {ltv:.0%} 받는다고 치면 내 돈이 **{won(need_cash)}** 필요 (집값의 {1-ltv:.0%} + 취득세·비용 {extra:.0%}). 지금 {won(have)} 있음" + (f" (보증금 {won(deposit)} 포함)" if deposit else "") + ".")
        pay = annuity(home_price * ltv, mort_rate, mort_years)
        yn = years_to(need_cash, have, monthly_net)
        if yn == 0:
            L.append(f"- 내 돈은 이미 된다. 다음 질문은 대출 {won(home_price*ltv)} 의 월 원리금 **{won(pay)}** (연 {mort_rate:.0%}·{mort_years}년) 을 지금 남는 돈 {won(monthly_net)} 에서 낼 수 있느냐다" + (" — 된다. 사고 나면 남는 돈은 " + won(monthly_net - pay) + "." if monthly_net >= pay else f" — **{won(pay - monthly_net)} 모자란다.** 집값을 낮추거나 소득이 오르기 전엔 무리."))
        else:
            L.append("| 시나리오 | 월 모으는 돈 | 걸리는 시간 |"); L.append("|---|---:|---:|")
            for name, mo in scen:
                L.append(f"| {name} | {won(mo)} | {y(years_to(need_cash, have, mo))} |")
            L.append(f"\n사고 나서는 월 원리금 **{won(pay)}** (대출 {won(home_price*ltv)}, 연 {mort_rate:.0%}·{mort_years}년) 가 고정지출에 얹힌다. 지금 남는 돈 {won(monthly_net)} 과 비교해 보면 " + ("감당 범위." if monthly_net >= pay else f"**{won(pay - monthly_net)} 모자란다** — 모으는 것과 별개로 소득이 더 필요하다는 뜻."))
            if yn is None:
                L.append("\n지금 남는 돈으로는 이 집에 못 간다. 절약 문제가 아니라 소득·집값·지역·둘이서의 문제다. 목표 집값을 바꿔 다시 보려면 profile.yaml options.home_goal_price.")
            elif yn > 15:
                L.append(f"\n{yn:.0f}년. 한두 푼 아껴서 되는 거리가 아니다. 월 +100만이면 {y(years_to(need_cash, have, monthly_net + 1_000_000))} — 차이는 소비가 아니라 소득 쪽에서 난다.")
            else:
                L.append(f"\n{yn:.1f}년이면 현실적인 거리다. 한 칸 위로 가면 {y(years_to(need_cash, have, monthly_net + 300_000))}.")
        L.append("")
    elif has_home:
        L.append("## 4. 집")
        L.append(f"- 이미 주택(또는 주택 대출)이 있다. 부동산 {won(realestate)}, 부채 {won(bs['total_liabilities'])}. 여기서의 질문은 '살 수 있나'가 아니라 대출을 언제 얼마나 갚을지다.")
        L.append("")
    L.append("## 5. 투자, 지금 하는 방식")
    if port_total > 1 and active:
        L.append(f"- 적극형으로 보인다: 자산의 {inv_share:.0%} 가 투자, 최근 {len(buy_months)}개월 매수 이체. 보유 {won(port_total)} 중 개별주·섹터가 {sat_share:.0%}.")
        holdings = sorted(((str(i.get("상품명") or ""), float(i.get("평가금액") or 0), float(i.get("투자원금") or 0)) for i in status.investments), key=lambda x: -x[1])
        top3 = holdings[:3]; top3_share = sum(v for _, v, _ in top3) / port_total
        if top3_share >= 0.5:
            L.append(f"- 상위 3종목({', '.join(n_ for n_, _, _ in top3)})이 투자자산의 **{top3_share:.0%}**. 이 셋이 곧 내 포트폴리오다. 셋 중 하나가 반토막 나면 전체가 {max(v for _, v, _ in top3)/port_total*0.5:.0%} 빠진다.")
        zero = [(n_, c) for n_, v, c in holdings if c and v == 0]        # 뱅샐이 평가 0으로 잡는 비상장·거래정지
        live = [(n_, v, c) for n_, v, c in holdings if c and v > 0]
        gain = sum(v - c for _, v, c in live); cost = sum(c for _, _, c in live)
        if cost:
            note = " (평가 0원인 " + ", ".join(n_ for n_, _ in zero) + f" 원금 {won(sum(c for _, c in zero))} 은 제외 — 비상장이면 프로필 manual_assets 값이 진짜)" if zero else ""
            if gain > 0:
                L.append(f"- 원금 {won(cost)} → 평가 {won(cost + gain)} ({gain/cost:+.0%}){note}. 이 수익의 대부분이 상위 몇 종목에서 나왔다면 실력일 수도, 그 종목의 해였을 수도 있다. 내년에도 같으리란 보장은 데이터에 없다.")
            else:
                L.append(f"- 원금 {won(cost)} → 평가 {won(cost + gain)} ({gain/cost:+.0%}){note}. 손실 상태에서 개별주 집중은 '회복까지 버티기'가 전략이 된다 — 그게 의도인지만 확인.")
        if sat_share >= 0.7:
            L.append(f"- 이 구성이면 지수가 -30% 나는 해에 개별주는 보통 그보다 크게 빠진다. 대략 **{won(port['위성(개별주·섹터)']*0.4)}** 가 사라지는 장면을 견딜 수 있는지가 질문. 견딜 수 있으면 그대로, 아니면 새로 넣는 돈만 지수 ETF로 — 팔 필요는 없다.")
        else:
            L.append("- 지수와 개별주가 섞여 있어 하락장에서 반은 버틴다.")
    elif port_total > 1:
        L.append(f"- 관망형으로 보인다: 투자자산 {won(inv_total)} (자산의 {inv_share:.0%}), 최근 {len(recent)}개월 새로 넣은 달 {len(buy_months)}. 바로 쓸 수 있는 돈이 {idle_months:.1f}개월치 놀고 있다.")
        L.append(f"- 이 돈이 파킹통장에 있으면 연 {won(idle_cash*0.03)} 정도, 지수 ETF면 기대 {won(idle_cash*0.07)} 정도. 어느 쪽이든 '결정을 안 한 채로 두는 것'보다는 낫다.")
    else:
        L.append(f"- 투자자산이 없다. 바로 쓸 수 있는 돈 {won(idle_cash)} 중 변동지출 3개월치({won(var_total*3)})를 빼면 **{won(max(idle_cash - var_total*3, 0))}** 는 놀고 있는 돈이다. 이걸 뭘로 할지가 첫 결정이고, 상품 이름은 그다음이다.")
    if iv.get("high_rate_loans"):
        L.append("- 금리 5% 넘는 대출이 있다. 투자 수익률보다 확실한 5%다.")
    L.append("")
    L.append("## 6. 바꿀 수 있는 손잡이 (강요 아님)")
    knobs = []
    if SUBS_avg > 30_000:
        knobs.append(f"구독 {won(SUBS_avg)}/월 중 안 쓰는 것 → 그만큼이 위 표 '월 +' 에 들어간다")
    if conv > 200_000:
        knobs.append(f"외식·배달·카페 {won(conv)}/월 — 반으로 줄이면 +{won(conv*0.5)}/월" + (f", 집까지 {y(years_to(need_cash, have, monthly_net + conv*0.5))}" if home_price and not has_home and years_to(need_cash, have, monthly_net) else ""))
    if ups_txt:
        knobs.append("최근 늘어난 것: " + ups_txt + " — 의도한 건지만 확인")
    if not knobs:
        knobs.append("소비 쪽에 큰 손잡이가 없다. 남는 돈을 자동이체로 어디에 둘지가 유일한 결정")
    for k in knobs[:3]:
        L.append(f"- {k}")
    L.append("")
    L.append("## 7. 한 줄로")
    if home_price and not has_home and years_to(need_cash, have, monthly_net) is None:
        L.append(f"- 지금 남는 돈 {won(monthly_net)}/월은 집으로 가는 길이 아니라 종잣돈을 키우는 길이다. 10년 뒤 {won(fv(seed, monthly_net, 10))}. 이 돈을 어디 둘지만 정하면 된다.")
    elif home_price and not has_home and years_to(need_cash, have, monthly_net):
        L.append(f"- 집까지 {y(years_to(need_cash, have, monthly_net))}. 월 +50만이면 {y(years_to(need_cash, have, monthly_net + 500_000))}. 그 50만이 어디서 나올지는 6번 손잡이 중 고르면 된다.")
    elif home_price and not has_home:
        L.append(f"- 집 살 내 돈은 된다. 결정은 월 원리금 {won(annuity(home_price*ltv, mort_rate, mort_years))} 을 안고 갈지, 종잣돈 {won(seed)} 을 굴릴지 둘 중 하나다.")
    else:
        L.append(f"- 매달 {won(monthly_net)} 남고, 10년이면 {won(fv(seed, monthly_net, 10))}. 이 돈을 어디 둘지가 전부다.")
    (OUT / "insight.md").write_text("\n".join(x for x in L if x is not None), encoding="utf-8")

    # ---------- ⑧ 부록: 투자 기초 정석 (읽어주지 않음, 원하면 보여줌)
    X = ["# 부록 — 투자 기초 재무제표·정석 체크 (참고용, 본문에서 읽어주지 않음)", f"> {fw['disclaimer']}", ""]
    if xlsx_out:
        X.append(f"- 투자 기초 양식 자동 채움: `{xlsx_out.name}`")
    X.append("| 지표 | 값 | 투자 기초 기준 |"); X.append("|---|---:|---|")
    X.append(f"| 저축률 | {savings_rate:.0%} | 20% 미만 주의 · 30% 이상 우수 |")
    X.append(f"| 수지 차액 (미파악 지출) | {won(gap)} | 0에 가까울수록 파악 완료 |")
    X.append(f"| 부채비율 | {debt_ratio:.0%} | 낮을수록 안전 |")
    X.append(f"| 투자 가능 종잣돈 | {won(seed)} | 현금성+투자자산 (연금·부동산 제외) |")
    lo, hi = ck["insurance_ratio"]
    X.append(f"| 보장성 보험료 | {won(insur)} = 급여의 {(insur/salary if salary else 0):.1%} | 세후 급여의 3~5% |")
    X.append(f"| 통신비 | {won(telecom) if telecom else '항목 없음'} | 알뜰폰 1~2만원대와 비교 |")
    X.append(f"| 주간 용돈 | 변동지출 ÷ 4 = {won(var_total/4)} | 변동지출을 고정지출처럼 |")
    gross_year = income_total * 12 * ck["gross_from_net"]
    X.append(f"| 계절지출 예산 | 세전 연봉 {won(gross_year)} × 10% = {won(gross_year*0.1)} | 비상금·파킹 잔액 {won(emergency)} |")
    if port_total > 1:
        X.append(f"| 코어(대표지수) 비중 | {core_share:.0%} | 최소 50% |")
    X.append("")
    X.append("코어-새틀라이트 배분 예시(보수 90:10 / 예시 40·10·40·10 / 공격 60:40)와 ETF 후보는 `templates/investment_baseline.yaml`.")
    (OUT / "insight_투자참고.md").write_text("\n".join(X), encoding="utf-8")

    tp = OUT / "financial_profile.md"
    if tp.exists():
        body = tp.read_text(encoding="utf-8").split("\n# 지금 페이스면")[0].split("\n# 깨달음")[0].rstrip()
        tp.write_text(body + "\n\n" + "\n".join(x for x in L if x is not None), encoding="utf-8")
    print(f"✔ 거울 → {OUT/'insight.md'} (+ 부록, xlsx)  남는 돈 {won(monthly_net)}/월 · 종잣돈 {won(seed)} · 집 {'있음' if has_home else (y(years_to(need_cash, have, monthly_net)) if home_price else '-')}")


if __name__ == "__main__":
    main()
