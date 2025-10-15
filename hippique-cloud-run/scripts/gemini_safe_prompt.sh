#!/usr/bin/env bash
set -euo pipefail
MODEL="${MODEL:-$(gemini models list | awk 'NR==1{print $1}')}"
INPUT="${1:-ping}"
TRIES=3

echo "[i] Model: $MODEL"
for i in $(seq 1 $TRIES); do
  echo "[i] try $i/$TRIES (non-stream)" >&2
  if gemini prompt -m "$MODEL" -i "$INPUT" --no-stream --json; then
    exit 0
  fi
  sleep 3
done

echo "[!] All non-stream tries failed, last attempt with streaming..." >&2
gemini prompt -m "$MODEL" -i "$INPUT"
