#!/usr/bin/env python3
"""AI 추정 단계 — 확인필요 묶음을 AI(대화 중인 Codex/Claude)가 먼저 추측하고, 사람은 틀린 것만 고친다.

  python3 scripts/suggest.py --prepare   ledger의 확인필요 묶음 → private/setup/04_추정_요청.md (AI가 읽고 suggestions.csv 를 쓴다)
  python3 scripts/suggest.py --promote   사용자가 확인한 추정(확정=Y 또는 --all) → private/rules.csv 로 승격, suggestions 에서 제거

suggestions.csv 컬럼: 묶음,카테고리,세부,신뢰도,근거,고정비,확정
신뢰도 규칙(ggplab/banksalad-autobudget 에서 가져옴): 가맹점명으로 업종이 분명 0.8~0.95 · 업종은 알겠으나 용도가 갈림 0.5~0.7 · 판매자를 특정 못함 0.4 이하.
0.6 미만은 build 에서 무시된다. 결정적 신호(사용자 답·품목·룰)는 추정으로 덮지 않는다.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import date

import yaml

from common import LEDGER, PRIVATE, SETUP, TEMPLATES, won

SUG = LEDGER / "suggestions.csv"
COLS = ["묶음", "카테고리", "세부", "신뢰도", "근거", "고정비", "확정"]


def prepare() -> None:
    with open(LEDGER / "ledger.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["상태"] != "확인필요":
            continue
        from common import normalize_merchant
        k = normalize_merchant(r["내용"]) + ("|이체" if r["타입"] == "이체" else "")
        groups[k].append(r)
    with open(TEMPLATES / "categories.yaml", encoding="utf-8") as f:
        cats = yaml.safe_load(f)
    allowed = list(cats["expense"]) + list(cats["income"]) + list(cats["transfer"])
    existing = {}
    if SUG.exists():
        with open(SUG, encoding="utf-8-sig", newline="") as f:
            existing = {r["묶음"]: r for r in csv.DictReader(f) if r.get("묶음")}
    L = ["# AI 추정 요청", "",
         "> **AI에게**: 아래 묶음마다 카테고리·세부·신뢰도·근거를 정해 `private/ledger/suggestions.csv` 에 한 줄씩 쓴다 (컬럼: 묶음,카테고리,세부,신뢰도,근거,고정비,확정 — 확정은 비워둔다).",
         "> 신뢰도: 가맹점명으로 업종이 분명 0.8~0.95 · 업종은 알겠으나 용도가 갈림 0.5~0.7 · 판매자를 특정 못함(PG사·송금·숫자만) 0.4 이하. 모르면 낮게. 0.6 미만은 적용되지 않으니 억지로 채우지 않는다.",
         "> 카테고리는 아래 목록 안에서만: " + ", ".join(allowed),
         "> 이체(|이체)는 사람 송금이면 '가족' 또는 '자산거래'(보증금·부동산·대출) 또는 '내부이체', 판단 불가면 0.3.",
         "> CSV 규칙: 근거·세부에 **쉼표를 쓰지 않는다** (필요하면 ·). 묶음은 아래 표의 첫 열을 글자 그대로.",
         "> 다 쓰면 `sh scripts/run.sh` → 03_확인필요.md 의 'AI 추정' 표를 사용자에게 보여주고 틀린 것만 받는다.", ""]
    L.append("| 묶음 | 건수 | 합계 | 계좌 | 예시(내용 · 품목 · 뱅샐분류) | 기존 추정 |")
    L.append("|---|---:|---:|---|---|---|")
    for k, lst in sorted(groups.items(), key=lambda kv: -sum(abs(int(r["금액"])) for r in kv[1])):
        s = sum(abs(int(r["금액"])) for r in lst)
        accs = sorted({r["계좌"] for r in lst})
        ex = lst[-1]
        item = f" · {ex['품목'][:40]}" if ex.get("품목") else ""
        old = existing.get(k)
        oldtxt = f"{old['카테고리']}/{old.get('세부','')} {old.get('신뢰도','')}" if old else ""
        L.append(f"| {k} | {len(lst)} | {won(s)} | {', '.join(accs)[:40]} | {ex['내용']}{item} · {ex['근거'][:30]} | {oldtxt} |")
    SETUP.mkdir(parents=True, exist_ok=True)
    (SETUP / "04_추정_요청.md").write_text("\n".join(L), encoding="utf-8")
    if not SUG.exists():
        with open(SUG, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(COLS)
    print(f"✔ 확인필요 묶음 {len(groups)}개 → {SETUP/'04_추정_요청.md'}\n  AI가 {SUG} 를 채운 뒤 sh scripts/run.sh")


def promote(all_: bool) -> None:
    if not SUG.exists():
        sys.exit("suggestions.csv 가 없습니다.")
    with open(SUG, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    keep, move = [], []
    for r in rows:
        ok = all_ or (r.get("확정") or "").strip().upper() in ("Y", "O", "맞아", "확정")
        try:
            conf = float(r.get("신뢰도") or 0)
        except ValueError:
            conf = 0
        (move if ok and conf >= 0.6 and r.get("카테고리") else keep).append(r)
    rules_p = PRIVATE / "rules.csv"
    if not rules_p.exists():
        rules_p.write_text((TEMPLATES / "rules.csv").read_text(encoding="utf-8"), encoding="utf-8")
    with open(rules_p, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in move:
            kw = r["묶음"].split("|")[0]
            w.writerow([kw, r["카테고리"], r.get("세부", ""), (r.get("고정비") or "N").upper()[:1], "", f"AI 추정 확정 {date.today()} (신뢰도 {r.get('신뢰도','')})"])
    with open(SUG, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in COLS} for r in keep)
    print(f"✔ 룰로 승격 {len(move)}건 → {rules_p}   (남은 추정 {len(keep)}건)")


if __name__ == "__main__":
    if "--prepare" in sys.argv:
        prepare()
    elif "--promote" in sys.argv:
        promote("--all" in sys.argv)
    else:
        print(__doc__)
