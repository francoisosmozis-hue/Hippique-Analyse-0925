#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-.}"
TARGETS="$(tools/list_targets.sh | xargs -I{} echo "$ROOT/{}" | tr '\n' ' ')"
mkdir -p .out
tools/pack_chunk.sh prompts/VERIFY_PROMPT.md .out/verify_chunk.txt $TARGETS
tools/gem_run.sh .out/verify_chunk.txt | tee .out/verify_report.md
