#!/usr/bin/env bash
set -euo pipefail
LOG_DIR="${LOG_DIR:-"$HOME/gemini_logs"}"
MODEL="${MODEL:-gemini-1.5-pro}"
mkdir -p "$LOG_DIR"

ts="$(date +%Y%m%d_%H%M%S)"
prompt="${1:-}"
if [[ -z "$prompt" ]]; then
  echo "Usage: $0 'Votre prompt ici'" >&2
  exit 1
fi

# 1) Sauvegarde du prompt
echo "{\"ts\":\"$ts\",\"type\":\"prompt\",\"model\":\"$MODEL\",\"text\":$(printf '%s' "$prompt" | jq -Rs .)}" >> "$LOG_DIR/session.jsonl"

# 2) Appel CLI (JSON recommandé)
resp_file="$LOG_DIR/resp_${ts}.json"
gemini prompt -m "$MODEL" -i "$prompt" --no-stream --json | tee "$resp_file"

# 3) Index JSONL
echo "{\"ts\":\"$ts\",\"type\":\"response\",\"model\":\"$MODEL\",\"file\":\"$resp_file\"}" >> "$LOG_DIR/session.jsonl"
