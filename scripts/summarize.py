#!/usr/bin/env python3
"""2단계: ledger.csv + 현황 시트 + profile → AI 재무 도우미에 넘길 요약 (거래 한 줄도 안 나감).

사용:  python3 scripts/summarize.py [export.xlsx]
출력:  private/out/cashflow_monthly.csv   월별 수입·고정·변동·저축이체·순현금흐름·저축률
       private/out/category_monthly.csv   카테고리별 월 금액
       private/out/balance_sheet.json     자산·부채·순자산 (위탁분 분리, 제외 계좌 제외)
       private/out/financial_profile.md      사람이 읽는 한 장 요약 — 이것만 AI 재무 도우미/AI에 준다
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from statistics import mean

from common import LEDGER, OUT, find_exports, load_profile, load_status, won

LIQUID_KINDS = {"checking", "savings", "pay", "cash"}


def main(argv: list[str]) -> None:
    prof = load_profile()
    files = find_exports(argv[1:] or None)
    status = load_status(files[-1])
    members = {m["id"]: m for m in prof["household"]["members"]}
    hh_labels = {m["label"] for m in prof["household"]["members"]
                 if m.get("role") == "self" or m.get("shared_household")}
    accounts = {a["name"]: a for a in prof["accounts"]}

    with open(LEDGER / "ledger.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("ledger.csv 가 비어 있습니다. build_ledger.py 먼저.")

    # ---- 월별 현금흐름 (가구 구성원 귀속만)
    M = defaultdict(lambda: defaultdict(int))
    C = defaultdict(lambda: defaultdict(int))     # (월, 카테고리) → 금액
    V = defaultdict(lambda: defaultdict(int))     # (월, 카테고리) → 변동비만
    SUBS = defaultdict(int)                       # 월 → 구독·멤버십 합계
    for r in rows:
        if r["귀속"] not in hh_labels or r["상태"] == "제외":
            continue
        mo, amt, st, cat = r["월"], int(r["금액"]), r["상태"], r["카테고리"]
        if st == "내부이체" or cat == "내부이체":
            continue
        if st == "저축이체":
            M[mo]["저축이체"] += -amt          # 나가면 +, 회수되면 -
            continue
        if st == "자산거래":
            M[mo]["자산거래"] += -amt          # 부동산·보증금·대출: 현금흐름 밖, 별도 표시
            continue
        if st == "확인필요":
            M[mo]["확인필요"] += abs(amt)      # 수입/지출에 넣지 않는다 — 답이 오면 그때 들어간다
            continue
        if st == "추정":
            M[mo]["추정"] += abs(amt)          # 집계에는 넣되 얼마가 추정인지 따로 센다
        if cat == "수입" or (amt > 0 and r["타입"] == "수입"):
            M[mo]["수입"] += amt
            C[mo]["수입/" + (r["세부"] or "기타")] += amt
        elif amt < 0 or r["타입"] == "지출":
            M[mo]["지출"] += -amt
            M[mo]["고정" if r["고정비"] == "Y" else "변동"] += -amt
            C[mo][cat] += -amt
            if r["고정비"] != "Y":
                V[mo][cat] += -amt
            if cat == "구독" or r["세부"] in ("OTT", "소프트웨어", "멤버십"):
                SUBS[mo] += -amt
        else:  # 양수인데 지출 카테고리 = 환불/취소
            M[mo]["지출"] += -amt
            M[mo]["변동"] += -amt
            C[mo][cat] += -amt

    months = sorted(M)
    # 마지막 달이 부분 월(export 시점)이면 표시만 하고 평균에서는 뺀다
    full_months = months[1:-1] if len(months) > 2 else months
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "cashflow_monthly.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["월", "수입", "지출", "고정지출", "변동지출", "순현금흐름", "저축률", "저축·투자 이체(순)", "자산거래(순유출)", "확인필요금액", "완전한달"])
        for mo in months:
            m = M[mo]
            net = m["수입"] - m["지출"]
            rate = (net / m["수입"]) if m["수입"] else 0
            w.writerow([mo, m["수입"], m["지출"], m["고정"], m["변동"], net, f"{rate:.2f}", m["저축이체"], m["자산거래"], m["확인필요"], "Y" if mo in full_months else "N"])
    cats = sorted({c for mo in C for c in C[mo]})
    with open(OUT / "category_monthly.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["카테고리"] + months + ["월평균(완전한달)"])
        for c in cats:
            avg = mean([C[mo][c] for mo in full_months]) if full_months else 0
            w.writerow([c] + [C[mo][c] for mo in months] + [int(avg)])

    # ---- 재무상태 (현황 시트 + 프로필 귀속/위탁)
    bs = {"exported_at": status.exported_at, "assets": defaultdict(float), "liabilities": defaultdict(float),
          "custodial": [], "excluded": [], "unmapped": []}
    inv_by_name = {i["상품명"]: i for i in status.investments}
    for a in status.assets:
        if not a["value"]:
            continue
        acc = accounts.get(a["name"])
        grp = a["group"] or ""
        kind = acc["kind"] if acc else {"자유입출금 자산": "checking", "저축성 자산": "savings", "전자금융 자산": "pay",
                                        "투자성 자산": "investment", "연금 자산": "pension", "현금 자산": "cash",
                                        "보험 자산": "insurance"}.get(grp, "other")
        if acc is None and a["name"] in inv_by_name:
            kind = "investment"
        if acc is None:
            bs["unmapped"].append(a["name"])
        owner = acc["owner"] if acc else "me"
        role = acc["role"] if acc else "saving"
        v = a["value"]
        if role == "exclude":
            bs["excluded"].append({"name": a["name"], "value": v}); continue
        if role == "custodial" and acc.get("custody"):
            c = acc["custody"]
            part = v * float(c["share"]) if "share" in c else min(v, float(c.get("amount", 0)))
            bs["custodial"].append({"name": a["name"], "of": members.get(c["of"], {}).get("label", c["of"]), "value": part})
            v -= part
        if owner not in members or not (members[owner].get("role") == "self" or members[owner].get("shared_household")):
            bs["custodial"].append({"name": a["name"], "of": members.get(owner, {}).get("label", owner), "value": v}); continue
        bs["assets"][kind] += v
    for l in status.liabilities:
        if l["value"]:
            bs["liabilities"][l["group"] or "부채"] += l["value"]
    # 뱅샐에 없는 자산·부채 (부동산, 비상장주식, 전세보증금, 사적 채무 …) — 프로필 manual_assets / manual_liabilities
    bs["manual"] = []
    for a in prof.get("manual_assets", []) or []:
        v = float(a.get("value") or 0)
        if not v:
            continue
        owner = a.get("owner", "me")
        if a.get("custody"):
            c = a["custody"]; part = v * float(c["share"]) if "share" in c else min(v, float(c.get("amount", 0)))
            bs["custodial"].append({"name": a["name"], "of": members.get(c["of"], {}).get("label", c["of"]), "value": part}); v -= part
        if owner in members and not (members[owner].get("role") == "self" or members[owner].get("shared_household")):
            bs["custodial"].append({"name": a["name"], "of": members[owner]["label"], "value": v}); continue
        bs["assets"][a.get("kind", "other")] += v
        bs["manual"].append({"name": a["name"], "kind": a.get("kind", "other"), "value": v, "note": a.get("note", "")})
    for l in prof.get("manual_liabilities", []) or []:
        v = float(l.get("value") or 0)
        if v:
            bs["liabilities"][l.get("kind", "기타부채")] += v
            bs["manual"].append({"name": l["name"], "kind": "부채·" + l.get("kind", "기타부채"), "value": -v, "note": l.get("note", "")})
    total_a = sum(bs["assets"].values()); total_l = sum(bs["liabilities"].values())
    bs["total_assets"], bs["total_liabilities"], bs["net_worth"] = total_a, total_l, total_a - total_l
    liquid = sum(v for k, v in bs["assets"].items() if k in LIQUID_KINDS)
    avg_exp = mean([M[m]["지출"] for m in full_months]) if full_months else 0
    avg_inc = mean([M[m]["수입"] for m in full_months]) if full_months else 0
    avg_fix = mean([M[m]["고정"] for m in full_months]) if full_months else 0
    avg_sav = mean([M[m]["저축이체"] for m in full_months]) if full_months else 0
    bs["liquid_assets"] = liquid
    bs["runway_months"] = round(liquid / avg_exp, 1) if avg_exp else None
    bs["loans"] = [{"name": l["상품명"], "lender": l["금융사"], "balance": l["대출잔액"], "limit": l["대출원금"],
                    "rate": l["대출금리"], "maturity": str(l["대출만기일"])[:10]} for l in status.loans]
    inv_p = sum(float(i["투자원금"] or 0) for i in status.investments)
    inv_v = sum(float(i["평가금액"] or 0) for i in status.investments)
    bs["investments"] = {"count": len(status.investments), "principal": inv_p, "value": inv_v,
                         "return_pct": round((inv_v - inv_p) / inv_p * 100, 1) if inv_p else None,
                         "by_broker": {}}
    for i in status.investments:
        bs["investments"]["by_broker"][i["금융사"]] = bs["investments"]["by_broker"].get(i["금융사"], 0) + float(i["평가금액"] or 0)
    bs["insurance_count"] = len(status.insurance)

    # ---- 투자 여력 (이 킷의 존재 이유) --------------------------------------------
    opt = prof.get("options", {}) or {}
    nb = int(opt.get("baseline_months", 3))            # 투자 여력은 최근 N개월 기준 (이사·목돈 달에 평균이 왜곡되지 않게)
    recent = full_months[-nb:] if full_months else []
    avg_inc = mean([M[m]["수입"] for m in recent]) if recent else 0
    avg_exp = mean([M[m]["지출"] for m in recent]) if recent else 0
    avg_fix = mean([M[m]["고정"] for m in recent]) if recent else 0
    avg_sav = mean([M[m]["저축이체"] for m in recent]) if recent else 0
    bs["runway_months"] = round(liquid / avg_exp, 1) if avg_exp else None
    em_m = float(opt.get("emergency_months", 6))
    retire_age = int(opt.get("retire_age", 60))
    rr = float(opt.get("return_rate", 0.04))
    spend_ratio = float(opt.get("retire_spend_ratio", 0.7))
    hi_rate = float(opt.get("high_rate_debt", 0.05)) * 100
    upcoming = sum(float(u.get("amount") or 0) for u in (prof.get("upcoming") or []))
    emergency = avg_exp * em_m
    investable_now = max(0.0, liquid - emergency - upcoming)
    net_cf = avg_inc - avg_exp                       # 저축이체는 지출에 안 들어 있음 → 이게 총 월 투자가능액
    headroom = net_cf - avg_sav                      # 이미 저축·투자로 보내는 것을 뺀 추가 여력
    fixed_ratio = (avg_fix / avg_inc) if avg_inc else None
    pension = bs["assets"].get("pension", 0.0)
    pension_names = {a["name"] for a in prof["accounts"] if a.get("kind") == "pension"}
    pension_monthly = 0.0
    for r in rows:
        if r["상태"] == "저축이체" and r["월"] in full_months and int(r["금액"]) < 0 and any(n and n in (r["근거"] + r["내용"]) for n in pension_names):
            pension_monthly += -int(r["금액"])
    pension_monthly = pension_monthly / len(full_months) if full_months else 0.0
    age = None
    try:
        age = int(status.person.get("연령")) if status.person.get("연령") is not None else None
    except (TypeError, ValueError):
        age = None
    years = (retire_age - age) if age is not None else None
    proj = None
    if years is not None and years > 0:
        proj = pension * (1 + rr) ** years + pension_monthly * 12 * (((1 + rr) ** years - 1) / rr if rr else years)
    retire_need = avg_exp * spend_ratio * 12 * 25    # 4% 룰: 연지출 × 25
    hi_loans = [l for l in bs["loans"] if l["balance"] and float(l["rate"] or 0) >= hi_rate]
    inv_total = bs["assets"].get("investment", 0.0)
    bs["investor"] = {
        "liquid": liquid, "emergency_reserve": emergency, "upcoming": upcoming, "investable_now": investable_now,
        "monthly_net_cashflow": net_cf, "monthly_already_saving": avg_sav, "monthly_headroom": headroom,
        "fixed_cost_ratio": fixed_ratio, "pension_assets": pension, "pension_monthly": pension_monthly,
        "age": age, "retire_age": retire_age, "years_to_retire": years, "pension_projection": proj,
        "retire_need_4pct": retire_need, "high_rate_loans": hi_loans,
        "investment_assets": inv_total, "investment_share": (inv_total / total_a) if total_a else None,
        "baseline_months": recent,
        "assumptions": {"emergency_months": em_m, "return_rate": rr, "retire_spend_ratio": spend_ratio, "high_rate_debt_pct": hi_rate},
    }
    bs["assets"] = dict(bs["assets"]); bs["liabilities"] = dict(bs["liabilities"])
    with open(OUT / "balance_sheet.json", "w", encoding="utf-8") as f:
        json.dump(bs, f, ensure_ascii=False, indent=2, default=str)

    # 같은 달은 갱신하고 새 달은 누적하는 자산 스냅샷
    asset_history_path = OUT / "asset_monthly.csv"
    asset_cols = ["월", "총자산", "총부채", "순자산", "유동자산", "입출금", "저축", "투자", "연금", "부동산"]
    history = {}
    if asset_history_path.exists():
        with open(asset_history_path, encoding="utf-8-sig", newline="") as f:
            history = {r["월"]: r for r in csv.DictReader(f)}
    snapshot_month = (status.exported_at or months[-1])[:7]
    history[snapshot_month] = {
        "월": snapshot_month, "총자산": int(total_a), "총부채": int(total_l), "순자산": int(total_a-total_l),
        "유동자산": int(liquid), "입출금": int(bs["assets"].get("checking", 0)),
        "저축": int(bs["assets"].get("savings", 0)), "투자": int(bs["assets"].get("investment", 0)),
        "연금": int(bs["assets"].get("pension", 0)), "부동산": int(bs["assets"].get("realestate", 0)),
    }
    with open(asset_history_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=asset_cols)
        w.writeheader(); w.writerows(history[m] for m in sorted(history))

    # ---- 한 장 요약
    hh = prof["household"]
    L = [f"# 재무 프로필 요약 — {hh.get('label','')}", f"> 생성: summarize.py · export {status.exported_at} · 완전한 달 {full_months[0] if full_months else '-'}~{full_months[-1] if full_months else '-'} 기준"]
    unconfirmed = sum(1 for a in prof["accounts"] if "_hint" in a or "_why" in a)
    if unconfirmed:
        L.append(f"> ⚠️ **인터뷰 전 초안** — 계좌 {unconfirmed}개의 성격이 자동 추정값입니다. 인터뷰 후 숫자가 달라질 수 있습니다.")
    L.append("")
    iv = bs["investor"]
    sane = avg_inc > 0 and avg_exp > 0 and avg_inc >= avg_exp * 0.2
    L.append(f"## 투자 여력 (핵심 4줄) — 최근 {len(iv['baseline_months'])}개월({iv['baseline_months'][0] if iv['baseline_months'] else '-'}~{iv['baseline_months'][-1] if iv['baseline_months'] else '-'}) 기준")
    unres_recent = mean([M[m]["확인필요"] for m in recent]) if recent else 0
    if unres_recent:
        L.append(f"> 확인필요 월평균 **{won(unres_recent)}** 는 아직 수입·지출 어디에도 안 들어가 있습니다 (인터뷰·AI 추정으로 줄어듭니다).")
    if not sane:
        L.append(f"> ⚠️ 아직 계산하지 않습니다 — 월 수입 {won(avg_inc)} / 지출 {won(avg_exp)} 로 비정상입니다. 보통 급여가 '이체'로 잡혀 수입원에 없거나, 큰 이체가 지출로 들어간 경우입니다. 인터뷰(수입원·계좌 성격·사람 송금)를 마치면 자동으로 채워집니다.")
        L.append("")
    if sane:
      L.append("| 질문 | 답 | 근거 |"); L.append("|---|---:|---|")
      L.append(f"| 지금 투자 가능한 돈 | **{won(iv['investable_now'])}** | 유동자산 {won(iv['liquid'])} − 비상금 {won(iv['emergency_reserve'])}({iv['assumptions']['emergency_months']:.0f}개월치 지출)" + (f" − 예정지출 {won(iv['upcoming'])}" if iv['upcoming'] else "") + " |")
      L.append(f"| 매달 투자 가능한 돈 | **{won(iv['monthly_net_cashflow'])}** | 수입 {won(avg_inc)} − 지출 {won(avg_exp)}. 이미 저축·투자로 {won(iv['monthly_already_saving'])} 보내는 중 → 추가 여력 {won(iv['monthly_headroom'])} |")
      if iv["years_to_retire"] is not None and iv["pension_projection"] is not None:
          pct = iv["pension_projection"] / iv["retire_need_4pct"] if iv["retire_need_4pct"] else 0
          L.append(f"| 노후 대비 | 연금자산 {won(iv['pension_assets'])}, 월 납입 {won(iv['pension_monthly'])} → {iv['retire_age']}세에 약 **{won(iv['pension_projection'])}** | 필요액 {won(iv['retire_need_4pct'])}(은퇴 후 연지출×25)의 **{pct:.0%}**. 연 {iv['assumptions']['return_rate']:.0%} 가정 |")
      else:
          L.append(f"| 노후 대비 | 연금자산 {won(iv['pension_assets'])}, 월 납입 {won(iv['pension_monthly'])} | 나이 정보 없음 → 프로필 options.retire_age 와 현황 시트 확인 |")
      if iv["high_rate_loans"]:
          L.append("| 빚 먼저? | **예** — " + ", ".join(f"{l['lender']} {l['name']} {won(l['balance'])}@{l['rate']}%" for l in iv["high_rate_loans"]) + f" | 금리 {iv['assumptions']['high_rate_debt_pct']:.0f}% 이상 대출은 기대수익보다 높음 |")
      else:
          L.append(f"| 빚 먼저? | 아니오 | 금리 {iv['assumptions']['high_rate_debt_pct']:.0f}% 이상 잔액 대출 없음 |")
      L.append(f"| (참고) 고정비 비율 | {iv['fixed_cost_ratio']:.0%} of 수입 | 투자자산 비중 {iv['investment_share']:.0%} of 총자산 |" if iv["fixed_cost_ratio"] is not None and iv["investment_share"] is not None else "")
    L.append("")
    L.append("## 가구")
    L.append("- 구성: " + ", ".join(f"{m['label']}({m['role']}{', 별도가계' if m.get('role')!='self' and not m.get('shared_household') else ''})" for m in hh["members"]))
    L.append("")
    L.append(f"## 월 현금흐름 (최근 {len(iv['baseline_months'])}개월 평균)")
    L.append("| 항목 | 월평균 |"); L.append("|---|---:|")
    L.append(f"| 수입 | {won(avg_inc)} |"); L.append(f"| 지출 | {won(avg_exp)} |")
    L.append(f"| └ 고정지출 | {won(avg_fix)} ({avg_fix/avg_exp:.0%} of 지출) |" if avg_exp else "| └ 고정지출 | - |")
    L.append(f"| 순현금흐름 | {won(avg_inc-avg_exp)} |")
    L.append(f"| 저축률 | {(avg_inc-avg_exp)/avg_inc:.0%} |" if avg_inc else "| 저축률 | - |")
    L.append(f"| 저축·투자 이체(순) | {won(avg_sav)} |")
    L.append("")
    # ---- 줄일 수 있는 곳 (최근 N개월 변동비 기준)
    if sane and recent:
        prev = full_months[-2*nb:-nb] if len(full_months) >= 2*nb else []
        var_avg = {c: mean([V[m][c] for m in recent]) for c in {c for m in recent for c in V[m]}}
        top_var = sorted(var_avg.items(), key=lambda x: -x[1])[:6]
        conv_cats = {"식사", "카페/간식"}
        conv_sub = {"배달", "외식", "카페", "편의점", "디저트"}
        conv = mean([sum(-int(r["금액"]) for r in rows if r["월"] == m and r["귀속"] in hh_labels and r["상태"] not in ("제외", "내부이체", "저축이체", "자산거래", "확인필요") and int(r["금액"]) < 0 and (r["카테고리"] in conv_cats or r["세부"] in conv_sub)) for m in recent])
        subs = mean([SUBS[m] for m in recent])
        L.append("## 줄일 수 있는 곳 (변동비, 최근 " + str(len(recent)) + "개월 평균)")
        L.append(f"- 변동비 월 **{won(mean([M[m]['변동'] for m in recent]))}** (지출의 {mean([M[m]['변동'] for m in recent])/avg_exp:.0%}). 고정비 {won(avg_fix)} 는 계약을 바꿔야 줄어든다.")
        L.append("| 변동비 카테고리 | 월평균 | 수입 대비 | 10% 줄이면 |"); L.append("|---|---:|---:|---:|")
        for c, v in top_var:
            L.append(f"| {c} | {won(v)} | {v/avg_inc:.0%} | +{won(v*0.1)}/월 |")
        L.append(f"- 먹는 데 편하게 쓰는 돈(외식·배달·카페·편의점): 월 **{won(conv)}** ({conv/avg_inc:.0%} of 수입)")
        if subs:
            L.append(f"- 구독·멤버십: 월 **{won(subs)}** (연 {won(subs*12)}) — 안 쓰는 것 하나만 끊어도 바로 여력")
        if prev:
            prev_avg = {c: mean([C[m][c] for m in prev]) for c in {c for m in prev for c in C[m]}}
            cur_avg = {c: mean([C[m][c] for m in recent]) for c in {c for m in recent for c in C[m]}}
            ups = sorted(((c, cur_avg[c] - prev_avg.get(c, 0)) for c in cur_avg if not c.startswith("수입/") and cur_avg[c] - prev_avg.get(c, 0) > 50_000), key=lambda x: -x[1])[:3]
            if ups:
                L.append("- 이전 " + str(nb) + "개월보다 늘어난 것: " + ", ".join(f"{c} +{won(d)}/월" for c, d in ups))
        var_total = mean([M[m]["변동"] for m in recent])
        for pct in (0.1, 0.2):
            gain = var_total * pct
            fut = gain * 12 * (((1 + rr) ** 10 - 1) / rr) if rr else gain * 120
            L.append(f"- 변동비 {pct:.0%} 줄이면 월 여력 +{won(gain)} → 연 {won(gain*12)} → 10년 투자 시(연 {rr:.0%}) 약 {won(fut)}")
        L.append("")
    L.append("## 월별")
    L.append("| 월 | 수입 | 지출 | 고정 | 변동 | 순현금흐름 | 저축이체 | 자산거래 | 확인필요 |"); L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for mo in months:
        m = M[mo]
        flag = "" if mo in full_months else " *"
        L.append(f"| {mo}{flag} | {m['수입']:,} | {m['지출']:,} | {m['고정']:,} | {m['변동']:,} | {m['수입']-m['지출']:,} | {m['저축이체']:,} | {m['자산거래']:,} | {m['확인필요']:,} |")
    L.append("\n\\* 부분 월 (평균에서 제외)\n")
    L.append("## 지출 카테고리 월평균 (상위 12)")
    L.append("| 카테고리 | 월평균 |"); L.append("|---|---:|")
    avgs = sorted(((c, mean([C[mo][c] for mo in full_months]) if full_months else 0) for c in cats if not c.startswith("수입/")), key=lambda x: -x[1])
    for c, v in avgs[:12]:
        L.append(f"| {c} | {won(v)} |")
    L.append("")
    L.append("## 재무상태 (export 시점)")
    L.append("| 항목 | 금액 |"); L.append("|---|---:|")
    for k, v in sorted(bs["assets"].items(), key=lambda x: -x[1]):
        L.append(f"| 자산·{k} | {won(v)} |")
    for k, v in bs["liabilities"].items():
        L.append(f"| 부채·{k} | -{won(v)} |")
    L.append(f"| **순자산** | **{won(bs['net_worth'])}** |")
    L.append(f"| 유동자산 / 월지출 | {bs['runway_months']}개월 |")
    if bs.get("manual"):
        L.append("\n프로필 직접 입력 항목: " + ", ".join(f"{c['name']} {won(c['value'])}" for c in bs["manual"]))
    if bs["custodial"]:
        L.append("\n위탁·타인 귀속 (순자산에서 제외): " + ", ".join(f"{c['name']}({c['of']}) {won(c['value'])}" for c in bs["custodial"]))
    if bs["excluded"]:
        L.append("\n집계 제외 계좌: " + ", ".join(f"{c['name']} {won(c['value'])}" for c in bs["excluded"]))
    if bs["unmapped"]:
        L.append(f"\n프로필에 없는 자산 항목 {len(bs['unmapped'])}개 (기본값 나/저축으로 평가): " + ", ".join(bs["unmapped"][:12]) + (" …" if len(bs["unmapped"]) > 12 else ""))
    L.append("")
    if bs["loans"]:
        L.append("## 대출")
        L.append("| 상품 | 잔액 | 한도 | 금리 | 만기 |"); L.append("|---|---:|---:|---:|---|")
        for l in bs["loans"]:
            L.append(f"| {l['lender']} {l['name']} | {won(l['balance'])} | {won(l['limit'])} | {l['rate']}% | {l['maturity']} |")
        L.append("")
    inv = bs["investments"]
    if inv["count"]:
        L.append("## 투자")
        L.append(f"- 상품 {inv['count']}개 · 원금 {won(inv['principal'])} · 평가 {won(inv['value'])} · 수익률 {inv['return_pct']}%")
        L.append("- 증권사별 평가: " + ", ".join(f"{k} {won(v)}" for k, v in sorted(inv["by_broker"].items(), key=lambda x: -x[1])))
        L.append("")
    L.append(f"## 보험\n- 보유 {bs['insurance_count']}건 (상세는 export 현황 시트)\n")
    unres_total = sum(M[m]["확인필요"] for m in months)
    sug_total = sum(M[m]["추정"] for m in months)
    L.append(f"## 데이터 품질\n- 확인필요 잔여 금액 합계 {won(unres_total)} → `private/setup/03_확인필요.md`\n- AI 추정으로 분류된 금액 {won(sug_total)} (신뢰도 0.6 이상, 사용자 확인 전)")
    (OUT / "financial_profile.md").write_text("\n".join(L), encoding="utf-8")
    print(f"✔ {len(months)}개월 · 완전한 달 {len(full_months)} · 순자산 {won(bs['net_worth'])} · 유동 {bs['runway_months']}개월")
    print(f"  {OUT/'financial_profile.md'}\n  {OUT/'cashflow_monthly.csv'}\n  {OUT/'balance_sheet.json'}")


if __name__ == "__main__":
    main(sys.argv)
