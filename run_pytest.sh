#!/usr/bin/env bash
# --- Exécution fiable de pytest avec src/ visible ---
set -euo pipefail
cd "$(dirname "$0")"

# 🔧 Initialise PYTHONPATH s'il est vide
: "${PYTHONPATH:=}"

export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
echo "[DEBUG] PYTHONPATH=$PYTHONPATH"

pytest "$@"
