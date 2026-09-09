#!/bin/sh
# 매달 이것만: build_ledger → summarize → (확인필요 있으면) 추정 요청 생성
set -e
cd "$(dirname "$0")/.."
python3 scripts/build_ledger.py "$@"
python3 scripts/summarize.py "$@"
python3 scripts/insight.py
python3 scripts/investment_interview.py
python3 scripts/dashboard.py
if grep -q "^## " "${CASHFLOW_PRIVATE:-private}/setup/03_확인필요.md" 2>/dev/null; then
  python3 scripts/suggest.py --prepare | tail -1
fi
echo
echo "→ ${CASHFLOW_PRIVATE:-private}/out/dashboard.html 에서 표·차트 확인. 요약은 out/financial_profile.md, 미결은 setup/03_확인필요.md"
