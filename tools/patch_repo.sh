#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-.}"
TARGETS="$(tools/list_targets.sh | xargs -I{} echo "$ROOT/{}" | tr '\n' ' ')"
mkdir -p .out
tools/pack_chunk.sh prompts/PATCH_PROMPT.md .out/patch_chunk.txt $TARGETS
tools/gem_run.sh .out/patch_chunk.txt | tee .out/patch_plan.md
echo
echo ">> Applique les diffs manuellement ou avec 'git apply -p0' si le format s'y prête."
