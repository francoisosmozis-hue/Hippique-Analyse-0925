#!/usr/bin/env bash
set -euo pipefail
MODEL=${MODEL:-gemini-2.5-pro}
INPUT="${1:-/dev/stdin}"
gemini --model "$MODEL" < "$INPUT"

