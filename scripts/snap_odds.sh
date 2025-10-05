#!/usr/bin/env bash
set -euo pipefail
TZ=${TZ:-Europe/Paris}
DATE=${1:-$(TZ=$TZ date +%F)}
OUT=${2:-data/pmu}

# Heuristique simple: si on est à plus de 20 minutes du départ moyen (~pré-course) => h30, sinon h5
# (Tu peux remplacer par une logique précise via l'heure de départ si tu veux).
TAG=${3:-}
if [[ -z "$TAG" ]]; then
  HOUR=$(TZ=$TZ date +%H)
  if (( 10#${HOUR} <= 15 )); then TAG=h30; else TAG=h5; fi
fi

echo "[i] Snap odds ${TAG} pour ${DATE} -> ${OUT}"
. .venv/bin/activate
python scripts/pmu_odds.py --date "$DATE" --out "$OUT" --tag "$TAG"
