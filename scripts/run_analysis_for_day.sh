#!/bin/bash
set -euo pipefail

SERVICE_URL="http://127.0.0.1:8080"
INPUT_FILE="day_runs/races_clean.json"
LOGDIR="logs"
mkdir -p "$LOGDIR"

echo ">> Starting analysis for races in $INPUT_FILE"

jq -c '.[]' "$INPUT_FILE" | while read -r R; do
  # Extract race details from JSON
  reunion=$(jq -r '.r_label' <<<"$R")
  course=$(jq -r '.c_label' <<<"$R")
  meeting=$(jq -r '.meeting' <<<"$R")
  label="${reunion}${course} ${meeting}"
  
  echo ">>> [H-30] Analyzing $label"
  curl -sS -X POST "$SERVICE_URL/analyse" \
    -H 'content-type: application/json' \
    -d "{\"phase\":\"H30\",\"reunion\":\"$reunion\",\"course\":\"$course\",\"budget\":5}" \
    | tee "$LOGDIR/${reunion}${course}_H30.log" >/dev/null

  echo ">>> [H-5]  Analyzing $label"
  curl -sS -X POST "$SERVICE_URL/pipeline/run" \
    -H 'content-type: application/json' \
    -d "{\"reunion\":\"$reunion\",\"course\":\"$course\",\"phase\":\"H5\",\"budget\":5}" \
    | tee "$LOGDIR/${reunion}${course}_H5.log" >/dev/null
done

echo ">> Analysis loop finished."
