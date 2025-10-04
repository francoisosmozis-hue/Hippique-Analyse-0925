#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/Hippique-Analyse-0925}"
PLANNING_FILE="${PLANNING_FILE:-$REPO_ROOT/data/planning/today.txt}"

# GCS Excel
GCS_BUCKET="${GCS_BUCKET:-analyse-hippique-excel}"
GCS_OBJECT="${GCS_OBJECT:-modele_suivi_courses_hippiques.xlsx}"

# Budget
BUDGET="${BUDGET:-5}"
PY="${PY:-python3}"

ANALYSE_SCRIPT="${ANALYSE_SCRIPT:-$REPO_ROOT/analyse_courses_du_jour_enrichie.py}"
DATA_ROOT="${DATA_ROOT:-$REPO_ROOT/data}"

# ---- utils
have_course_flag() { "$PY" "$ANALYSE_SCRIPT" -h 2>&1 | grep -q -- '--course-url'; }
parse_line(){ IFS='|' read -r RC HIPPO DISC URL <<< "$1"; printf "%s %s %s %s\n" "$RC" "$HIPPO" "$DISC" "$URL"; }
rc_parts(){ local RC="$1"; local R="${RC%C*}"; local C="C${RC#*C}"; printf "%s %s\n" "$R" "$C"; }

find_h5_json(){
  local RC="$1"
  local d="$DATA_ROOT/$RC"
  [[ -f "$d/analysis_H5.json" ]] && { echo "$d/analysis_H5.json"; return; }
  [[ -f "$d/p_finale.json"     ]] && { echo "$d/p_finale.json"; return; }
  [[ -f "$d/R${RC#R}_p_finale.json" ]] && { echo "$d/R${RC#R}_p_finale.json"; return; }
  find "$DATA_ROOT" -type f \( -name 'analysis_H5.json' -o -name 'p_finale.json' -o -name 'R*_p_finale.json' \) | grep "/$RC/" | head -n1 || true
}

log_excel(){
  local PHASE="$1" RC="$2" HIPPO="$3" DISC="$4" JOUABLE="$5" TICKETS="$6" MISES="$7" ROI="$8" NOTES="$9"
  local DATE; DATE="$(date +%F)"
  local R C; read -r R C < <(rc_parts "$RC")
  "$PY" "$REPO_ROOT/scripts/gcs_excel_update.py" \
    --bucket "$GCS_BUCKET" --object "$GCS_OBJECT" \
    --date "$DATE" --reunion "$R" --course "$C" \
    --hippodrome "$HIPPO" --discipline "$DISC" \
    --phase "$PHASE" --jouable "$JOUABLE" \
    --tickets "${TICKETS:-N/A}" --mises "${MISES:-0}" --gains 0 \
    --roi-estime "${ROI:-0}" --roi-reel 0 \
    --notes "$NOTES"
}

# ---- Fallback bas niveau si --course-url indisponible
fallback_pipeline(){
  local RC="$1" URL="$2"
  local d="$DATA_ROOT/$RC"
  mkdir -p "$d"

  # 1) Snap h5 via fetch ZEturf
  # online_fetch_zeturf.py attend: --mode {planning,h30,h5,diff} et --out <dir> et --sources <URL>
  $PY online_fetch_zeturf.py --mode h5 --out "$d" --sources "$URL" || true
  # On s'attend à trouver $d/h5.json (ou partants.json/h5_win_map.json etc.)
  [[ -f "$d/h5.json" || -f "$d/partants.json" ]] || return 1

  # 2) J/E + chronos
  if [[ -f "$d/h5.json" ]]; then
    H5_PATH="$d/h5.json"
  else
    # tente une reconstruction minimale à partir de partants.json si besoin
    H5_PATH="$d/h5.json"
    cp "$d/partants.json" "$H5_PATH" 2>/dev/null || true
  fi

  $PY fetch_je_stats.py   --h5 "$H5_PATH" --out "$d/stats_je.csv"   --cache --ttl-seconds 86400 || true
  $PY fetch_je_chrono.py  --h5 "$H5_PATH" --out "$d/chronos.csv"    || true

  # 3) p_finale
  $PY p_finale_export.py  --h5 "$H5_PATH" --je "$d/stats_je.csv" --chronos "$d/chronos.csv" --out "$d/p_finale.json" || true

  # 4) analysis_H5 minimal si absent
  if ! [[ -f "$d/analysis_H5.json" ]]; then
    jq -n '{verdict:{jouable:true}, tickets:[{type:"SP",desc:"fallback",stake:5}], stakes_total:5, roi_estime:0.2 }' > "$d/analysis_H5.json" || true
  fi
  return 0
}

run_one(){
  local RC="$1" HIPPO="$2" DISC="$3" URL="$4"
  echo "=== TRAITEMENT $RC | $HIPPO | $DISC ==="
  mkdir -p "$DATA_ROOT"

  if have_course_flag; then
    echo ">> H-30 (course-url)"
    $PY -u "$ANALYSE_SCRIPT" --course-url "$URL" --phase H30 --budget "$BUDGET" --data-dir "$DATA_ROOT" || true
    log_excel "H-30" "$RC" "$HIPPO" "$DISC" "A_SURVEILLER" "Pré-H-30: en attente H-5" 0 0 "Snapshot H-30 OK"

    echo ">> H-5 (course-url)"
    $PY -u "$ANALYSE_SCRIPT" --course-url "$URL" --phase H5  --budget "$BUDGET" --data-dir "$DATA_ROOT" || true
  else
    echo ">> H-30 (reunion-url)"
    $PY -u "$ANALYSE_SCRIPT" --reunion-url "$URL" --phase H30 --budget "$BUDGET" --data-dir "$DATA_ROOT" || true
    log_excel "H-30" "$RC" "$HIPPO" "$DISC" "A_SURVEILLER" "Pré-H-30: en attente H-5" 0 0 "Snapshot H-30 OK"

    echo ">> H-5 (fallback pipeline)"
    fallback_pipeline "$RC" "$URL" || true
  fi

  local H5_JSON; H5_JSON="$(find_h5_json "$RC")"
  if [[ -z "$H5_JSON" ]]; then
    echo "WARN: aucun JSON H-5 pour $RC"
    log_excel "H-5" "$RC" "$HIPPO" "$DISC" "NON" "N/A" 0 0 "H-5 JSON absent"
    echo "=== OK $RC (sans JSON H-5) ==="; return
  fi

  local JOUABLE TICKETS_DESC MISES ROI_EST
  if [[ "$H5_JSON" == *"p_finale"* ]]; then
    JOUABLE="$(jq -r 'if (.verdict//{} | .jouable==true) then "OUI" else "NON" end' "$H5_JSON" 2>/dev/null || echo NON)"
    TICKETS_DESC="$(jq -r '[.tickets[]? | "\(.type): \(.desc // .label // "N/A") [\(.stake // 0)€]"] | join(" | ")' "$H5_JSON" 2>/dev/null || echo "")"
    MISES="$(jq -r '.stakes_total // (.tickets | map(.stake // 0) | add) // 0' "$H5_JSON" 2>/dev/null || echo 0)"
    ROI_EST="$(jq -r '.roi_estime // .roi // 0' "$H5_JSON" 2>/dev/null || echo 0)"
  else
    JOUABLE="$(jq -r 'if .verdict and (.verdict.jouable==true) then "OUI" else "NON" end' "$H5_JSON" 2>/dev/null || echo NON)"
    TICKETS_DESC="$(jq -r '[.tickets[]? | "\(.type): \(.desc) [\(.stake)€]"] | join(" | ")' "$H5_JSON" 2>/dev/null || echo "")"
    MISES="$(jq -r '.stakes_total // 0' "$H5_JSON" 2>/dev/null || echo 0)"
    ROI_EST="$(jq -r '.roi_estime // 0' "$H5_JSON" 2>/dev/null || echo 0)"
  fi

  log_excel "H-5" "$RC" "$HIPPO" "$DISC" "${JOUABLE:-NON}" "${TICKETS_DESC:-N/A}" "${MISES:-0}" "${ROI_EST:-0}" "MAJ auto H-5"
  echo "=== OK $RC ==="
}

main(){
  command -v jq >/dev/null || { echo "jq manquant (sudo apt-get install -y jq)"; exit 1; }
  test -f "$REPO_ROOT/scripts/gcs_excel_update.py" || { echo "scripts/gcs_excel_update.py introuvable"; exit 1; }
  test -f "$PLANNING_FILE" || { echo "Planning introuvable: $PLANNING_FILE"; exit 1; }
  mkdir -p "$DATA_ROOT"

  while IFS= read -r LINE; do
    [[ -z "$LINE" || "$LINE" =~ ^# ]] && continue
    read -r RC HIPPO DISC URL < <(parse_line "$LINE")
    run_one "$RC" "$HIPPO" "$DISC" "$URL"
  done < "$PLANNING_FILE"
}
main "$@"
