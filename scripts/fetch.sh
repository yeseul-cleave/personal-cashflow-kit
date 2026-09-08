#!/bin/sh
# 자동 수집 한 방 — 묻지 않는다. 사람이 할 일은 (필요할 때만) 크롬 창 로그인 1회, 압축 비밀번호 1회.
#   sh scripts/fetch.sh                  # 로그인 확인 → 뱅샐 메일 찾기(계정 자동 감지) → zip 풀기 → 프로필 없으면 진단까지
#   sh scripts/fetch.sh --wait           # 뱅샐 메일이 아직 없으면 15분 기다리며 재확인
#   sh scripts/fetch.sh 2026_07 2026_08  # + 해당 월 쿠팡·네이버 (이미 있으면 건너뜀)
cd "$(dirname "$0")/.."
command -v node >/dev/null 2>&1 || { echo "❌ node 가 없습니다. https://nodejs.org 에서 LTS 설치 후 다시."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ python3 가 없습니다. https://python.org 에서 설치 후 다시."; exit 1; }
[ -f private/fetch.json ] || cp templates/fetch.json private/fetch.json
[ -d node_modules ] || [ -d "$HOME/.personal-cashflow-deps/node_modules" ] || [ -d "$HOME/.naver-receipts-deps/node_modules" ] || npm install --silent
python3 -c "import openpyxl, yaml" 2>/dev/null || python3 -m pip install -q -r requirements.txt 2>/dev/null \
  || python3 -m pip install -q --user -r requirements.txt 2>/dev/null \
  || python3 -m pip install -q --break-system-packages -r requirements.txt \
  || { echo "❌ 파이썬 패키지 설치 실패: python3 -m pip install -r requirements.txt 를 직접 실행해 보세요."; exit 1; }

node scripts/fetch/login_gmail.mjs || exit 1          # 세션 있으면 즉시 통과, 없으면 창 띄우고 기다림
WAIT=""; MONTHS=""
for a in "$@"; do case "$a" in --wait) WAIT="--wait";; *) MONTHS="$MONTHS $a";; esac; done
# 월 인자가 없으면: 프로필이 있는(매달) 경우 최근 2개월, 처음이면 최근 3개월을 품목 보강 대상으로
if [ -z "$MONTHS" ]; then
  n=3; [ -f private/profile.yaml ] && n=2
  MONTHS=$(python3 -c "
import datetime as d
t=d.date.today().replace(day=1); out=[]
for i in range($n):
    t=(t-d.timedelta(days=1)).replace(day=1) if i else t
    out.append(t.strftime('%Y_%m'))
print(' '.join(reversed(out)))")
fi
node scripts/fetch/fetch_banksalad.mjs $WAIT; rc=$?
case $rc in
  0) ;;
  3) echo "→ private/fetch.json 의 banksalad_zip_password 를 채우고  sh scripts/fetch.sh  다시."; exit 3;;
  2) exit 2;;
  *) exit $rc;;
esac
for ym in $MONTHS; do
  if python3 -c "import json,sys;c=json.load(open('private/fetch.json'));sys.exit(0 if c.get('coupang',True) else 1)" 2>/dev/null; then
    [ -f "private/enrich/coupang/$ym/쿠팡_주문_$ym.csv" ] || node scripts/fetch/fetch_coupang.mjs "$ym"
  fi
  if python3 -c "import json,sys;c=json.load(open('private/fetch.json'));sys.exit(0 if c.get('kurly',True) else 1)" 2>/dev/null; then
    [ -f "private/enrich/kurly/$ym/컬리_주문_$ym.csv" ] || node scripts/fetch/fetch_kurly.mjs "$ym"
  fi
  if python3 -c "import json,sys;c=json.load(open('private/fetch.json'));sys.exit(0 if c.get('naver') else 1)" 2>/dev/null; then
    [ -f "private/naver_auth.json" ] || node scripts/fetch/login_naver.mjs
    [ -f "private/enrich/naver/$ym/네이버페이_주문_$ym.csv" ] || node scripts/fetch/fetch_naver.mjs "$ym"
  fi
done
if [ ! -f private/profile.yaml ]; then
  python3 scripts/inspect_export.py
  cp private/setup/profile.draft.yaml private/profile.yaml          # 초안 그대로 1차 프로필 (인터뷰로 고쳐 나간다)
  [ -f private/rules.csv ] || cp templates/rules.csv private/rules.csv
  echo; echo "── 인터뷰 전 1차 결과 (계좌 성격은 추정값) ──"
fi
sh scripts/run.sh >/dev/null
sed -n '/^## 투자 여력/,/^## 가구/p' private/out/financial_profile.md | sed '$d'
echo "→ 전체: private/out/financial_profile.md · 인터뷰 질문지: private/setup/02_질문지.md"
