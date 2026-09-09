#!/usr/bin/env python3
"""현재 재무 상태에서 '다음 결정을 바꾸는 질문'만 만든다.

출력은 대시보드용 JSON과, AI가 한 번에 한 질문씩 읽을 질문지다.
답은 private/profile.yaml 의 investment_plan 에 저장한다.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from common import OUT, SETUP, find_exports, load_profile, load_status


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def won(v: float) -> str:
    return f"{round(v):,}원"


def main() -> None:
    profile = load_profile()
    plan = profile.get("investment_plan") or {}
    with (OUT / "balance_sheet.json").open(encoding="utf-8") as f:
        bs = json.load(f)
    cash = rows(OUT / "cashflow_monthly.csv")
    cats = rows(OUT / "category_monthly.csv")
    full = [r for r in cash if r.get("완전한달") == "Y"][-3:]
    avg = lambda key: sum(float(r.get(key) or 0) for r in full) / len(full) if full else 0

    monthly_net = avg("순현금흐름")
    liquid = float(bs.get("liquid_assets") or 0)
    pension = float((bs.get("assets") or {}).get("pension") or 0)
    realestate = float((bs.get("assets") or {}).get("realestate") or 0)
    debt = float(bs.get("total_liabilities") or 0)
    expense = avg("지출")
    runway = liquid / expense if expense else 0

    investments = bs.get("investments") or {}
    portfolio = float(investments.get("value") or 0)
    status = load_status(find_exports()[-1])
    holding_values = sorted((float(x.get("평가금액") or 0) for x in status.investments), reverse=True)
    top3_share = sum(holding_values[:3]) / portfolio if portfolio else 0

    category_values = []
    for r in cats:
        name = r.get("카테고리", "")
        if name.startswith("수입/"):
            continue
        value = float(r.get("월평균(완전한달)") or 0)
        if value > 0:
            category_values.append((name, value))
    category_values.sort(key=lambda x: x[1], reverse=True)
    cut_candidates = [{"category": name, "monthly": value, "ten_pct": value * .1,
                       "twenty_pct": value * .2} for name, value in category_values[:6]]

    has_home = realestate > 0 or debt > 0
    questions = [
        {
            "key": "home_direction",
            "title": "집의 다음 역할",
            "why": "현재 자료에는 주택과 대출이 함께 있어, 집 목표가 무엇인지에 따라 현금·연금·일반계좌 배분이 완전히 달라집니다.",
            "question": "다음 집 관련 목표는 무엇인가요?",
            "choices": ["현재 집 유지 + 대출 관리", "갈아타기", "추가 주택", "집보다 금융자산이 우선"] if has_home else ["첫 집 마련", "전세·월세 유지", "집보다 금융자산이 우선"],
        },
        {
            "key": "priority",
            "title": "돈의 1순위",
            "why": "같은 월 여유자금도 노후·집·자유투자 중 어디에 먼저 보내는지 알아야 계좌별 금액을 정할 수 있습니다.",
            "question": "앞으로 3년간 돈의 1순위는 무엇인가요?",
            "choices": ["현금 안전판", "집·대출", "노후·연금", "일반계좌 투자"],
        },
        {
            "key": "home_timing",
            "title": "집 결정 시점",
            "why": "3년 안에 쓸 돈과 10년 이상 둘 돈은 같은 방식으로 투자할 수 없습니다.",
            "question": "집과 관련해 큰돈을 쓸 가능성이 가장 높은 시점은 언제인가요?",
            "choices": ["3년 이내", "4~7년", "8년 이후", "계획 없음"],
        },
        {
            "key": "buyback_amount_basis",
            "title": "11월 바이백 실수령액",
            "why": "예정된 4.8억원이 세금·수수료 전인지 실제 통장에 남는 금액인지에 따라 2031년 분담금과 투자 가능액이 달라집니다.",
            "question": "11월 바이백 4.8억원은 세금과 비용을 뺀 실제 예상 실수령액인가요?",
            "choices": ["세후·비용후 실수령액", "세금·비용 전 금액", "아직 계산 전", "잘 모르겠음"],
        },
        {
            "key": "contribution_funding",
            "title": "분담금의 재원",
            "why": "총대출 6억원이 현재 이주비대출 3억원을 포함한 금액이라면, 추가 대출 3억원을 분담금에 쓰는지에 따라 4.8억원 중 투자 가능한 돈이 크게 달라집니다.",
            "question": "분담금 3.56억원 중 약 3억원은 입주 때 추가 대출로 내고, 현금은 약 5,600만원과 후불이자만 낼 계획인가요?",
            "choices": ["맞음", "분담금은 현금으로 낼 예정", "대출·현금 비율 미정", "다른 계획"],
        },
        {
            "key": "drawdown_capacity",
            "title": "하락 때 지킬 금액",
            "why": f"현재 투자자산은 {won(portfolio)}이고 상위 3개 집중도는 약 {top3_share:.0%}입니다. 추상적인 성향보다 실제 하락장에서 지켜야 할 돈을 알아야 합니다.",
            "question": "투자자산이 30% 하락해도 3년 동안 꺼내 쓰지 않을 수 있는 금액은 어느 정도인가요?",
            "choices": ["거의 전부", "절반 정도", "일부만", "잘 모르겠음"],
        },
        {
            "key": "pension_constraint",
            "title": "연금의 역할",
            "why": "연금은 오래 묶이는 대신 세제상 장점이 있을 수 있어, 유동성 필요와 함께 판단해야 합니다.",
            "question": "연금에 넣은 돈을 은퇴 전까지 쓰지 않아도 되나요?",
            "choices": ["그렇다", "일부만 가능", "아직 묶기 어렵다", "잘 모르겠음"],
        },
    ]
    next_question = next((q for q in questions if not plan.get(q["key"])), None)
    answered = sum(bool(plan.get(q["key"])) for q in questions)

    result = {
        "as_of": bs.get("exported_at"),
        "status": {"answered": answered, "total": len(questions)},
        "observed": [
            {"label": "월 여유자금", "value": monthly_net},
            {"label": "바로 쓸 수 있는 돈", "value": liquid, "note": f"최근 지출 약 {runway:.1f}개월치"},
            {"label": "연금", "value": pension},
            {"label": "투자자산", "value": portfolio, "note": f"상위 3개 비중 약 {top3_share:.0%}"},
            {"label": "주택 / 부채", "value": realestate, "note": f"부채 {won(debt)}"},
        ],
        "cut_candidates": cut_candidates,
        "answers": {q["key"]: plan.get(q["key"]) for q in questions if plan.get(q["key"])},
        "next_question": next_question,
        "outputs": ["월 여유자금 사용 순서", "현금·집·연금·일반계좌 월 배분표", "현재 보유종목 유지·추가매수 판단 기준", "10%·20% 지출조정 시 목표 도달 변화", "다음 점검일과 다시 볼 조건"],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    SETUP.mkdir(parents=True, exist_ok=True)
    (OUT / "next_step.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# 다음 스텝 — 투자·집 설계 인터뷰", "", f"> 자료 기준일 {result['as_of']} · 이미 아는 사실은 다시 묻지 않고, 답을 바꾸는 질문만 한 번에 하나씩 묻는다.", "",
          "## 지금 확인된 사실", "", "| 항목 | 현재 관찰 |", "|---|---:|"]
    for item in result["observed"]:
        md.append(f"| {item['label']} | {won(item['value'])}" + (f" · {item['note']}" if item.get("note") else "") + " |")
    md += ["", "## 인터뷰 규칙", "", "- 아래 순서대로 한 번에 하나만 묻는다.", "- 답은 `private/profile.yaml`의 `investment_plan`에 즉시 저장한다.", "- 답이 모두 모이면 계좌별 금액표·조건·다음 점검일을 만든다.", ""]
    for i, q in enumerate(questions, 1):
        state = f"답: {plan[q['key']]}" if plan.get(q["key"]) else "미응답"
        md += [f"### {i}. {q['title']} — {state}", "", q["why"], "", q["question"], "", " / ".join(q["choices"]), ""]
    (SETUP / "05_투자설계_질문지.md").write_text("\n".join(md), encoding="utf-8")
    print(f"✔ 투자 설계 인터뷰 → {SETUP/'05_투자설계_질문지.md'}")


if __name__ == "__main__":
    main()
