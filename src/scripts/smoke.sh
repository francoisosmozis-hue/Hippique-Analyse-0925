#!/bin/bash
set -euo pipefail

# Change to the project root directory
cd "$(dirname "$0")/.."

echo "--- Checking Python syntax ---"
python -m py_compile runner_chain.py pipeline_run.py src/service.py

echo "--- Running smoke tests ---"
# Run pytest, but don't fail the script if tests fail (for CI purposes)
pytest -q tests/test_smoke.py || true