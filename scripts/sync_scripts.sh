#!/usr/bin/env bash
set -euo pipefail

DEST="$HOME/hippique-orchestrator"
SRC1="$HOME/work/Hippique-Analyse-0925-sweep"
SRC2="$HOME/Hippique-Analyse-0925"

# modules indispensables (tu peux en ajouter si besoin)
files=(
  "module_dutching_pmu.py"
  "analyse_courses_du_jour_enrichie.py"
  "pipeline_run.py"
  "online_fetch_zeturf.py"
  "fetch_je_stats.py"
  "fetch_je_chrono.py"
  "simulate_ev.py"
  "simulate_wrapper.py"
  "validator_ev.py"
  "p_finale_export.py"
  "drive_sync.py"
  "get_arrivee_geny.py"
  "update_excel_with_results.py"
  "prompt_analyse.py"
)

mkdir -p "$DEST"

copy_if_exists () {
  local f="$1"
  for base in "$SRC1" "$SRC2" "$SRC1/scripts" "$SRC2/scripts"; do
    [ -f "$base/$f" ] && { cp "$base/$f" "$DEST/"; echo ">> Copied: $base/$f"; return 0; }
  done
  echo ">> Missing: $f" >&2
  return 1
}

ok=0; ko=0
for f in "${files[@]}"; do
  if copy_if_exists "$f"; then ok=$((ok+1)); else ko=$((ko+1)); fi
done

echo "=== Sync done: $ok copied, $ko missing ==="
