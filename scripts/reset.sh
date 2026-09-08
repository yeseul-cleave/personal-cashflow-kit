#!/bin/sh
# 깨끗한 상태로 되돌리기 — 지우지 않고 private/_archive/<시각>/ 로 옮긴다.
#   sh scripts/reset.sh          # exports·profile·rules·setup·ledger·out·enrich 를 아카이브. fetch.json·로그인 세션은 유지
#   sh scripts/reset.sh --all    # fetch.json·naver_auth.json 까지 (Gmail 크롬 프로필은 그대로)
cd "$(dirname "$0")/.."
ts=$(date +%Y%m%d-%H%M%S); dest="private/_archive/$ts"; mkdir -p "$dest"
for f in exports profile.yaml rules.csv setup ledger out enrich tools; do [ -e "private/$f" ] && mv "private/$f" "$dest/"; done
[ "$1" = "--all" ] && for f in fetch.json naver_auth.json; do [ -e "private/$f" ] && mv "private/$f" "$dest/"; done
echo "✔ private/ 초기화 → $dest 로 옮김 (되돌리려면 그 안의 것을 private/ 로)"
ls private
