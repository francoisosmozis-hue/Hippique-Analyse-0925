#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-.}"
TARGETS="$(tools/list_targets.sh | xargs -I{} echo "$ROOT/{}" | tr '\n' ' ')"
mkdir -p .out
tools/pack_chunk.sh prompts/AUDIT_PROMPT.md .out/audit_chunk.txt $TARGETS
tools/gem_run.sh .out/audit_chunk.txt | tee .out/audit_report.md
