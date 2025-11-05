#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:?Usage: BASE_URL=https://service-xxxx-uc.a.run.app $0}"

echo "→ GET ${BASE_URL}/__health"
curl -fsS "${BASE_URL}/__health" | jq .

echo "→ POST ${BASE_URL}/prompt/generate"
curl -fsS -X POST "${BASE_URL}/prompt/generate" \
  -H 'content-type: application/json' \
  -d '{"reunion":"R1","course":"C1","budget":5}' | jq .

echo "→ POST ${BASE_URL}/pipeline/run"
curl -fsS -X POST "${BASE_URL}/pipeline/run" \
  -H 'content-type: application/json' \
  -d '{"reunion":"R1","course":"C1","phase":"H5","budget":5}' | jq .

echo "Smoke Cloud OK."
