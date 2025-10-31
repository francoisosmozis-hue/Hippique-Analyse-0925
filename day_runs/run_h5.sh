#!/usr/bin/env bash
set -euo pipefail
SERVICE_URL="${SERVICE_URL:?missing}"
INPUT="${1:-day_runs/races_today.json}"

jq -c '.[]' "$INPUT" | while read -r R; do
  RNUM=$(jq -r '.reunion' <<<"$R")
  CNUM=$(jq -r '.course'  <<<"$R")
  LABEL=$(jq -r '.label'  <<<"$R")

  echo ">>> H-5 :: $LABEL"
  curl -sS -X POST "$SERVICE_URL/pipeline/run" \
    -H 'content-type: application/json' \
    -d "{\"reunion\":\"$RNUM\",\"course\":\"$CNUM\",\"phase\":\"H5\",\"budget\":5}" \
    | tee "logs/${RNUM}${CNUM}_H5.json" >/dev/null

  # Option : lire le verdict rapidement
  ANAL="data/${RNUM}${CNUM}/analysis_H5.json"
  if [[ -f "$ANAL" ]]; then
    echo "----- Résumé $RNUM$CNUM"
    jq '{course: .course_id, verdict: .verdict, roi_estime: .roi_estime, tickets: .tickets}' "$ANAL" || true
  fi
done
