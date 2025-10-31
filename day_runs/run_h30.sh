#!/usr/bin/env bash
set -euo pipefail
SERVICE_URL="${SERVICE_URL:?missing}"
INPUT="${1:-day_runs/races_today.json}"

jq -c '.[]' "$INPUT" | while read -r R; do
  URL=$(jq -r '.course_url // empty' <<<"$R")
  RNUM=$(jq -r '.reunion' <<<"$R")
  CNUM=$(jq -r '.course'  <<<"$R")
  LABEL=$(jq -r '.label'  <<<"$R")

  echo ">>> H-30 :: $LABEL"
  if [[ -n "$URL" ]]; then
    curl -sS -X POST "$SERVICE_URL/analyse" \
      -H 'content-type: application/json' \
      -d "{\"phase\":\"H30\",\"course_url\":\"$URL\",\"budget\":5}" \
      | tee "logs/${RNUM}${CNUM}_H30.json" >/dev/null
  else
    curl -sS -X POST "$SERVICE_URL/analyse" \
      -H 'content-type: application/json' \
      -d "{\"phase\":\"H30\",\"reunion\":\"$RNUM\",\"course\":\"$CNUM\",\"budget\":5}" \
      | tee "logs/${RNUM}${CNUM}_H30.json" >/dev/null
  fi
done
