#!/usr/bin/env bash
set -euo pipefail
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip wheel
[ -f requirements.txt ] && pip install -r requirements.txt || true
pip install pandas pyyaml beautifulsoup4 lxml openpyxl

mkdir -p out/smoke
if [ -f analyse_courses_du_jour_enrichie.py ]; then
  python analyse_courses_du_jour_enrichie.py \
    --phase H5 \
    --h30 data/smoke/h30.json \
    --h5  data/smoke/h5.json  \
    --budget 5 \
    --outdir out/smoke
elif [ -f pipeline_run.py ]; then
  python pipeline_run.py analyse \
    --phase H5 \
    --h30 data/smoke/h30.json \
    --h5  data/smoke/h5.json  \
    --budget 5 \
    --outdir out/smoke
else
  echo "❌ Aucun entrypoint pipeline trouvé."
  exit 1
fi

echo "✅ Smoke local terminé. Contenu out/smoke :"
ls -R out/smoke || true
