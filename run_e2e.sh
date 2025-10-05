#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] start: $(date '+%F %T')"
pwd

# Choix du fetcher existant
FETCH="online_fetch_zeturf.py"
[ -f "$FETCH" ] || FETCH="scripts/online_fetch_zeturf.py"
if [ ! -f "$FETCH" ]; then
  echo "[ERR] online_fetch_zeturf.py introuvable" >&2; exit 2
fi
echo "[INFO] FETCH=$FETCH"

# Course de test (modifiable)
COURSE_URL="${COURSE_URL:-https://www.zeturf.fr/fr/course/2025-09-06/R1C2-vincennes}"
echo "[INFO] COURSE_URL=$COURSE_URL"

OUTDIR="data/$(date +%Y%m%d_%H%M%S)_R1C2"
mkdir -p "$OUTDIR"

# Snap H30/H-30 puis H5/H-5
python "$FETCH" --course-url "$COURSE_URL" --snapshot H30 --out "$OUTDIR" \
|| python "$FETCH" --course-url "$COURSE_URL" --snapshot H-30 --out "$OUTDIR"

python "$FETCH" --course-url "$COURSE_URL" --snapshot H5 --out "$OUTDIR" \
|| python "$FETCH" --course-url "$COURSE_URL" --snapshot H-5 --out "$OUTDIR"

echo "[INFO] OUTDIR content:"; ls -l "$OUTDIR" || true

H30_JSON="$(ls "$OUTDIR"/*H30*.json "$OUTDIR"/*H-30*.json 2>/dev/null | head -1 || true)"
H5_JSON="$( ls "$OUTDIR"/*H5*.json  "$OUTDIR"/*H-5*.json  2>/dev/null | head -1 || true)"
echo "[INFO] H30_JSON=$H30_JSON"
echo "[INFO] H5_JSON=$H5_JSON"
[ -n "$H30_JSON" ] && [ -n "$H5_JSON" ] || { echo "[ERR] snapshots manquants"; exit 3; }

# Pipeline (essaie sous-commande 'analyse', sinon direct)
if python pipeline_run.py analyse --h30 "$H30_JSON" --h5 "$H5_JSON" --budget 5; then
  true
else
  python pipeline_run.py --h30 "$H30_JSON" --h5 "$H5_JSON" --budget 5
fi

# Résumé si présent
LAST_ANALYSIS="$(ls data/*/analysis_H5.json 2>/dev/null | tail -1 || true)"
if [ -f "$LAST_ANALYSIS" ]; then
  python - <<'PY'
import json,glob
paths=sorted(glob.glob('data/*/analysis_H5.json'))
d=json.load(open(paths[-1]))
print("[SUMMARY]",{
  "roi_global_est": d.get("validation",{}).get("roi_global_est"),
  "sp": d.get("validation",{}).get("sp"),
  "exotics_summary": d.get("validation",{}).get("exotics_summary")
})
PY
else
  echo "[WARN] analysis_H5.json non trouvé"
fi

echo "==> Dernières lignes tracking.csv (si dispo)"; tail -n+1 data/*/tracking.csv 2>/dev/null | tail -n 20 || true
echo "[INFO] end: $(date '+%F %T')"
