---
name: cashflow-setup
description: 뱅크샐러드 1년치 export로 개인 재무 프로필을 처음 세팅한다. "세팅 시작", "가계부 세팅", "내 재무 프로필 만들어줘", "export 넣었어" 같은 요청에 쓴다. 진단 → 근거 있는 인터뷰(한 번에 하나) → profile.yaml/rules.csv 기록 → 빌드 → 요약 낭독.
---

# cashflow-setup

저장소 루트는 이 스킬 파일의 상위 `../../..` (personal-cashflow-kit). 먼저 `AGENTS.md` 를 읽는다.

## 절차

1. 먼저 "사용자 이름과 뱅크샐러드 내보내기 메일을 받은 Gmail 주소를 알려주세요"라고 한 번 묻는다. 이메일은 로그인 계정 확인에만 쓰고 파일에 저장하지 않는다. 답을 받으면 `sh scripts/fetch.sh --wait` 실행. (설치·Gmail 세션 확인·계정 자동 감지·다운로드·해제·진단까지 스크립트가 함.) 이후 말을 거는 경우는 크롬 로그인 창이 떴을 때, 종료코드 2(뱅샐 메일 없음 → 앱에서 파일로 받기 안내, 15분 대기), 종료코드 3(압축 비밀번호 → 그때만 묻고 fetch.json 에 기록 후 재실행) 뿐. Gmail 번호·내보내기 여부·쿠팡/네이버 여부는 묻지 않는다. 사용자가 xlsx 를 직접 넣었으면 수집을 건너뛴다.
2. `private/setup/01_진단.md` 가 없으면 `python3 scripts/inspect_export.py`. 먼저 `02_질문지.md`의 "지금 생활의 1차 윤곽"(최근 3개 완성월 수입·카테고리 지출·생활/쇼핑·남은 돈)을 보여주고, 그다음 진단을 3~4줄로 요약한다. 장기 가상 시나리오는 인터뷰 뒤로 미룬다.
3. `private/setup/profile.draft.yaml` 을 `private/profile.yaml` 로 복사한다 (이미 있으면 덮어쓰지 말고 이어서). 처음 받은 사용자 이름을 본인 `household.members[].label`에 반영한다.
   `private/rules.csv` 가 없으면 `templates/rules.csv` 를 복사한다.
4. `private/setup/02_질문지.md` 순서로 **한 번에 한 질문**. 답을 받을 때마다:
   - 계좌 귀속·성격·위탁 → `profile.yaml` `accounts` 항목의 `owner`/`role`/`custody` 수정, `_hint` 삭제
   - 가족 구성 → `household.members`, 사람 이체 → `transfers.family` 또는 `accounts` 에 alias 추가
   - 반복 지출 → `recurring`, 수입 → `income`
   - 가맹점 카테고리 → `rules.csv` 한 줄 (키워드,카테고리,세부,고정비,귀속,메모)
   - 부동산·비상장·빌려준 돈 → `manual_assets` / `manual_liabilities`
5. B(계좌)·D(이체 상대)가 끝나면 `sh scripts/run.sh` 한 번 돌려 월별 표를 눈으로 검산한다. 이상치는 원인부터.
6. 질문지 끝 → `sh scripts/run.sh` → `python3 scripts/suggest.py --prepare` → **네가** `private/setup/04_추정_요청.md` 를 읽고 `private/ledger/suggestions.csv` 를 채운다(묶음,카테고리,세부,신뢰도,근거,고정비,확정) → `sh scripts/run.sh` → `03_확인필요.md` 의 "AI 추정" 표를 보여주고 틀린 것만 받는다 → 맞으면 `python3 scripts/suggest.py --promote --all` → 남은 확인필요만 큰 것부터. 잔여가 월지출 5% 아래면 종료.
7. `private/out/financial_profile.md` 를 읽고 쉬운 말로 요약해 준다. "투자 여력 (핵심 4줄)" 표부터. 가정값은 `profile.yaml` options(비상금 개월수·은퇴 나이·기대수익률·6개월 내 예정지출 `upcoming`)에서 바꾼다. 다음 달 절차(export 한 번 → "이번 달 마감")를 한 줄로 알려준다.

## 질문 형식

`**계좌명** (종류) — 근거 · → 누구 것 / 생활·저축·사업·위탁·제외?`
**목록은 종류별 묶음(카드/통장/간편결제/청약·저축/주식·ETF·펀드/연금/대출) + 마크다운 표를 질문지에서 그대로, 한 행도 줄이지 않고** 붙인다. 범위("31~58 투자 28개")로 합치지 않는다. **후보 없는 추상 질문 금지.** "~있나요?"라고 묻지 말고, 질문지에 붙은 목록(번호·금액)을 그대로 보여주고 번호로 고르게 한다. 목록이 없으면 `01_진단.md`에서 뽑아 붙인다.
선택지를 항상 붙이고, 추정이 강하면 "○○로 보이는데 맞나요?" 확인형으로.
반복 지출은 최근 3개월 중심으로 실제 날짜·금액·결제수단을 함께 보여주고, 연 1~2회 후보도 별도 표로 확인한다. 종목은 총액을 다시 묻지 않고 종목별 귀속만, 주거는 자가/전세/월세/가족 집/회사 제공 중에서 묻는다.

## 금지

- 거래 원문·계좌번호를 `private/` 밖 파일에 쓰지 않는다.
- 사용자 대신 "이건 엄마 돈일 것"이라고 정하지 않는다. 묻는다.
- `ledger.csv`, `out/` 을 손으로 고치지 않는다.
