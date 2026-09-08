#!/bin/sh
# 매달 이것만: build_ledger → summarize → (확인필요 있으면) 추정 요청 생성
set -e
cd "$(dirname "$0")/.."
python3 scripts/build_ledger.py "$@"
python3 scripts/summarize.py "$@"
python3 scripts/insight.py
if grep -q "^## " "${CASHFLOW_PRIVATE:-private}/setup/03_확인필요.md" 2>/dev/null; then
  python3 scripts/suggest.py --prepare | tail -1
fi
echo
echo "→ ${CASHFLOW_PRIVATE:-private}/out/financial_profile.md 확인. 미결은 setup/03_확인필요.md, AI 추정 요청은 setup/04_추정_요청.md"
