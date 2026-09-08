---
name: cashflow-monthly
description: 매달 뱅크샐러드 export를 넣은 뒤 재무 프로필을 갱신한다. "이번 달 마감", "○월 마감", "export 새로 넣었어", "재무 프로필 업데이트" 같은 요청에 쓴다. 빌드 → 새 확인필요만 질문 → 재빌드 → 지난달 대비 변화 보고.
---

# cashflow-monthly

저장소 루트는 `../../..` (personal-cashflow-kit). `AGENTS.md` 의 월 마감 모드를 따른다.

## 절차

1. `private/profile.yaml` 이 없으면 이 스킬 대신 `cashflow-setup` 으로.
2. 묻지 말고 `sh scripts/fetch.sh --wait <YYYY_MM>`. 받은 xlsx 파일명 기간이 이번 달을 안 덮으면 "앱에서 파일로 받기(최근 1년) 한 번 해 주세요" 한 줄 후 재실행.
3. 갱신 전 `private/out/cashflow_monthly.csv` 를 읽어 지난달 수치를 기억해 둔다.
4. `sh scripts/run.sh`.
5. `python3 scripts/suggest.py --prepare` → 네가 `suggestions.csv` 를 채움 → `sh scripts/run.sh`. `03_확인필요.md` 의 "AI 추정" 표는 확인만 받고(맞으면 `suggest.py --promote --all`), 남은 **이번 달 묶음**만 큰 것부터 묻는다. 답은 `rules.csv`(가맹점) 또는 `ledger/overrides.csv`(한 건: `거래키,카테고리,세부,귀속,고정비,메모`)에 적는다.
6. 다시 `sh scripts/run.sh`.
7. `private/out/financial_profile.md` 이번 달 줄을 지난달과 비교해 달라진 것 2~3개만 말한다. (수입·지출·고정비·저축이체·순자산)

## 새 계좌·카드가 나타났을 때

`build_ledger.py` 출력에 `계좌미등록` 이 있으면 그 계좌를 `profile.yaml` `accounts` 에 추가하는 질문을 먼저 한다 (누구 것 / 성격).
