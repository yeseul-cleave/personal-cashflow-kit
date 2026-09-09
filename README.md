# personal-cashflow-kit — "가계부 안 써도 되는 가계부"

뱅크샐러드 **1년치 export 파일 하나**를 넣고, AI와 **최대 20문 인터뷰**를 하면
그 뒤로는 매달 export 한 번에 내 **월 현금흐름·자산 구조 요약**이 나온다.
AI 재무 도우미(AI Financial Assistant)이 투자 조언을 할 때 필요한 "이 사람의 재무 형편"을 만드는 것이 목적이다.
결과의 첫 줄은 투자자가 정말 모르는 네 가지다: **지금 투자 가능한 돈 · 매달 투자 가능한 돈 · 노후 대비 현황 · 빚부터 갚아야 하는지.**

- 거래를 손으로 적지 않는다. 카테고리도 손으로 안 고른다. **AI가 근거를 들고 질문하고, 답만 한다.**
- 사람마다 다른 것(가족 구성, 계좌 귀속, 엄마 돈 섞인 투자계좌, 고정비 계약)은 전부 `private/profile.yaml` 한 파일에만 들어간다.
- 원본 거래는 내 컴퓨터 `private/`를 절대 떠나지 않는다. 밖으로 나가는 것은 `private/out/financial_profile.md` 한 장뿐이다.

## 30초 시작

```bash
git clone <this repo> && cd personal-cashflow-kit
python3 -m pip install -r requirements.txt && npm install
cp templates/fetch.json private/fetch.json      # Gmail 계정 번호·뱅샐 압축비번 채우기
npm run login:gmail                             # 크롬 창에서 Gmail 로그인 1회 (세션 저장)
# 뱅크샐러드 앱 → 마이 → 데이터 내보내기 → "파일로 받기" (기간: 최근 1년) → 메일로 옴
sh scripts/fetch.sh                             # 메일에서 zip 받아 private/exports/ 에 자동으로 품
python3 scripts/inspect_export.py               # 진단 + 프로필 초안 + 질문지
```

그다음은 Codex(또는 Claude Code)에서 **"세팅 시작"** 이라고 말하면 된다. AI가 사용자 이름과 뱅크샐러드 메일을 받은 Gmail 주소를 먼저 묻고 진행한다. 절차는 `SETUP.md`.
파일을 손으로 넣어도 된다: xlsx를 `private/exports/`에 두고 `inspect_export.py`부터.

## 폴더

```
personal-cashflow-kit/
├── README.md            ← 지금 이 파일
├── SETUP.md             ← 사람이 읽는 세팅 절차 (처음 한 번 + 매달)
├── AGENTS.md            ← AI(Codex·Claude)가 따르는 인터뷰·금지 규칙
├── requirements.txt     ← openpyxl, pyyaml
├── templates/
│   ├── profile.yaml     ← 프로필 양식 (주석이 설명서)
│   ├── rules.csv        ← 가맹점 룰 학습장 양식
│   ├── categories.yaml  ← 기본 카테고리 트리 (뱅샐 분류 + 확장)
│   ├── investment_baseline.yaml    ← 투자 기초 프레임 기준값·ETF 후보 (판정 기준은 코드가 아니라 여기)
│   └── external/        ← 선택 사항: 사용자가 직접 준비한 재무제표 엑셀 양식
├── scripts/
│   ├── inspect_export.py  ← 0단계: export 진단 → 01_진단.md · profile.draft.yaml · 02_질문지.md
│   ├── build_ledger.py    ← 1단계: 프로필+룰 적용 → ledger.csv · 03_확인필요.md
│   ├── suggest.py         ← 1.5단계: 확인필요를 AI가 먼저 추측(신뢰도) → 사람은 틀린 것만 → 룰로 승격
│   ├── summarize.py       ← 2단계: 월 현금흐름·재무상태 요약 → out/
│   ├── dashboard.py       ← 월별·카테고리·자산 상세를 표와 차트로 보는 로컬 HTML
│   ├── investment_interview.py ← 집·연금·일반계좌 설계 질문과 다음 설계 탭 데이터
│   ├── insight.py         ← 3단계: 거울 — 남는 돈·10년 시나리오·집·투자 성향 관찰 → out/insight.md (+ 투자 기초 부록·xlsx)
│   ├── run.sh             ← 1+2단계 한 방 + 추정 요청 생성 (매달 이것만)
│   ├── reset.sh           ← 처음부터 다시 (private 를 _archive 로 옮김)
│   ├── fetch.sh           ← 자동 수집 한 방: 뱅샐 메일 → exports/, 쿠팡·네이버 → enrich/
│   ├── fetch/             ← Gmail·네이버 수집기 (playwright + 크롬 전용 프로필, 로그인 1회)
│   └── common.py          ← export 파서 (거래 시트 + 현황 시트), 프로필/룰 로더, 품목 보강
├── .codex/skills/       ← Codex 스킬 (cashflow-setup, cashflow-monthly)
├── .claude/skills/      ← 같은 스킬의 Claude Code 판
└── private/             ← git 무시. 내 데이터 전부
    ├── fetch.json       ← 수집 설정 (Gmail 계정 번호, 뱅샐 압축비번, 쿠팡·네이버 on/off)
    ├── exports/         ← 뱅샐 xlsx 원본 (fetch.sh 가 채움)
    ├── enrich/          ← 쿠팡 주문·네이버페이 결제내역 (품목 보강용)
    ├── naver_auth.json  ← 네이버 로그인 세션 (npm run login:naver)
    ├── profile.yaml     ← 내 프로필 (templates/profile.yaml 복사해 인터뷰로 채움)
    ├── rules.csv        ← 내 가맹점 룰 (인터뷰 답이 쌓임)
    ├── setup/           ← 01_진단.md · profile.draft.yaml · 02_질문지.md · 03_확인필요.md
    ├── ledger/          ← ledger.csv (거래 단위 장부) · overrides.csv (거래 한 건 답)
    └── out/             ← financial_profile.md · insight.md · insight_투자참고.md · 투자기초_재무제표_자동.xlsx · cashflow_monthly.csv · balance_sheet.json
```

## 데이터 흐름

```
Gmail(뱅샐 메일) ──fetch.sh──▶ exports/*.xlsx ──inspect──▶ 진단 + 질문지 ──AI 인터뷰──▶ profile.yaml + rules.csv
Gmail(쿠팡·컬리 메일) ─fetch.sh─▶ enrich/coupang,kurly/ ┐                                          │
네이버페이 내역  ──fetch.sh──▶ enrich/naver/    ─┴──▶ build_ledger ◀────────────────────────┘
                                                        │  ledger.csv (귀속·카테고리·품목·고정비·상태)
                                                        ▼
                                                   summarize ──▶ out/financial_profile.md  ← 이것만 AI 재무 도우미에 준다
```

**품목 보강**: "쿠팡 -34,260"처럼 가맹점만 보이는 거래에 같은 금액·근접 날짜의 주문(쿠팡 메일 / 네이버페이 내역)을 붙여 품목을 채운다. 장터 거래는 품목으로 룰을 다시 적용해서 "쿠팡=온라인장보기"가 "기저귀=육아"로 바뀐다.

## 판정 우선순위 (build_ledger)

1. `overrides.csv` (거래 한 건에 대한 사용자 답)
2. 계좌 `role: exclude` → 제외
3. 이체: 카드대금 → 짝 매칭(±1일, 같은 금액, 다른 계좌) → 계좌 alias → 본인 이름 → `rules.csv` → 가족 이전 → **확인필요**
4. 지출·수입: `rules.csv` → 고정비 계약(recurring) → 수입원(income) → 뱅샐 자동분류 → **AI 추정(신뢰도 0.6 이상)** → **확인필요**

"확인필요"는 수입·지출 어디에도 넣지 않고 따로 센다. 답이 오면 그때 들어간다. AI 추정은 집계에 넣되 금액을 따로 보고하고, 사용자가 맞다고 하면 룰로 승격돼 다음 달부터 결정적 신호가 된다. (신호 우선순위와 신뢰도 규칙은 ggplab/banksalad-autobudget 에서 가져왔다. MIT)

## 사람마다 다른 걸 다루는 방법

| 상황 | 프로필에서 |
|---|---|
| 싱글 | `members` 에 `me` 하나만 |
| 배우자와 한 지갑 | `spouse` 에 `shared_household: true` → 배우자 export도 `exports/`에 넣으면 합산 |
| 부모님 카드가 내 이름에 연결 | 그 카드 `role: exclude` |
| 투자계좌에 엄마 돈 40% | `role: custodial, custody: {of: mom, share: 0.4}` → 순자산에서 빼고 "위탁 자산"으로 별도 표시 |
| 엄마에게 매달 용돈 | `transfers.family` 에 `{match: "엄마", category: 가족, sub: 부모님 용돈}` |
| 부동산·비상장주식 (뱅샐에 없음) | `manual_assets` 에 직접 |
| 사업 계좌 섞임 | 그 계좌 `role: business` + `options.business_split: true` |
| 부동산 잔금·보증금 같은 큰 이체 | `rules.csv` 에 카테고리 `자산거래` → 현금흐름 밖으로 분리 |

## 이 킷이 안 하는 것

- 쿠팡·컬리 앱이나 네이버 주문 페이지 직접 크롤링 — 봇차단 때문에 안 된다. 메일과 결제내역 페이지의 임베디드 JSON만 쓴다.
- 넘버스/엑셀에서 손으로 칠하기 — 없다. 답은 채팅으로 하고 AI가 `rules.csv`/`overrides.csv`에 적는다.
- 클라우드 동기화 — 없다. `private/`는 로컬. 백업은 각자.
