#!/usr/bin/env bash
set -euo pipefail
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip wheel
[ -f requirements.txt ] && pip install -r requirements.txt || true
pip install pandas pyyaml beautifulsoup4 lxml openpyxl

SMOKE_RACE_DIR="out/smoke/R1C1"
mkdir -p "$SMOKE_RACE_DIR"

# Create a dummy snapshot for runner_chain.py to use
cat <<EOF > "$SMOKE_RACE_DIR/snapshot_H5.json"
{
  "payload": {
    "course_id": "123456",
    "reunion": "R1",
    "course": "C1",
    "start_time": "2024-01-01T12:00:00",
    "runners": [
      {"num": "1", "odds": 2.0},
      {"num": "2", "odds": 3.0}
    ]
  }
}
EOF

# Copy other needed files if they exist
[ -f data/ci_sample/je_stats.csv ] && cp data/ci_sample/je_stats.csv "$SMOKE_RACE_DIR/je_stats.csv"
[ -f data/ci_sample/chronos.csv ] && cp data/ci_sample/chronos.csv "$SMOKE_RACE_DIR/chronos.csv"

# Run the new pipeline entrypoint
python scripts/runner_chain.py "$SMOKE_RACE_DIR"

echo "✅ Smoke local terminé. Contenu out/smoke :"
ls -R out/smoke || true
