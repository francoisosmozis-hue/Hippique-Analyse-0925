#!/bin/sh
set -eu
# shellcheck disable=SC3040
if set -o pipefail 2>/dev/null; then
  :
fi

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEFAULT_URL="https://www.zeturf.fr/fr/meeting/2024-09-25/paris-vincennes"
COURSE_URL=${1:-$DEFAULT_URL}
OUTPUT_DIR="$REPO_ROOT/out_smoke_h5"
PYTHON_BIN=${PYTHON:-python3}

printf '==> Lancement analyse H-5 sur %s\n' "$COURSE_URL"
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

"$PYTHON_BIN" "$REPO_ROOT/analyse_courses_du_jour_enrichie.py" \
  --course-url "$COURSE_URL" \
  --phase H5 \
  --data-dir "$OUTPUT_DIR" \
  --budget 5 \
  --kelly 0.5

analysis_path=$(find "$OUTPUT_DIR" -maxdepth 3 -name 'analysis_H5.json' -print -quit)
if [ -z "$analysis_path" ]; then
  echo "[ERREUR] Fichier analysis_H5.json introuvable" >&2
  exit 1
fi
analysis_dir=$(dirname "$analysis_path")

printf '\n==> Artefacts générés dans %s\n' "$analysis_dir"
ls -1 "$analysis_dir"

grep -F '"phase": "H5"' "$analysis_path" >/dev/null || {
  echo "[ERREUR] analysis_H5.json ne contient pas la phase H5" >&2
  exit 1
}

per_horse_path="$analysis_dir/per_horse_report.csv"
if [ ! -f "$per_horse_path" ]; then
  echo "[ERREUR] per_horse_report.csv manquant" >&2
  exit 1
fi
grep -E '^(num|horse)' "$per_horse_path" >/dev/null || {
  echo "[ERREUR] per_horse_report.csv ne semble pas contenir d'en-têtes" >&2
  exit 1
}

tracking_path="$analysis_dir/tracking.csv"
if [ ! -f "$tracking_path" ]; then
  echo "[ERREUR] tracking.csv manquant" >&2
  exit 1
fi
grep -E '(phase|H5)' "$tracking_path" >/dev/null || {
  echo "[ERREUR] tracking.csv ne contient pas de trace H5" >&2
  exit 1
}

snapshot_path=$(find "$OUTPUT_DIR" -maxdepth 4 -name 'snapshot_H5.json' -print -quit)
if [ -z "$snapshot_path" ]; then
  echo "[ERREUR] snapshot_H5.json introuvable" >&2
  exit 1
fi
grep -F '"phase": "H5"' "$snapshot_path" >/dev/null || {
  echo "[ERREUR] snapshot_H5.json ne contient pas la phase H5" >&2
  exit 1
}

printf '\n==> Vérification terminée : analyse H-5 OK\n'
