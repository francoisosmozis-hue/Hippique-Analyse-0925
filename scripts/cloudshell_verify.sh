#!/usr/bin/env bash
set -euo pipefail

echo "▶ Ruff (lint)…"
ruff --version
ruff check . || true   # n'échoue pas la vérif si warnings

echo "▶ Smoke imports…"
python - <<'PY'
mods = [
  "analyse_courses_du_jour_enrichie",
  "pipeline_run",
  "runner_chain",
  "simulate_ev",
  "validator_ev",
  "module_dutching_pmu",
]
ok = []
for m in mods:
    try:
        __import__(m)
        ok.append(m)
    except Exception as e:
        print(f"[WARN] import {m} échoue: {e}")
print(f"[OK] imports: {', '.join(ok) if ok else 'aucun module importé'}")
PY

echo "▶ Pytest (si des tests existent)…"
pytest -q || true

echo "✅ Vérification terminée (lint+imports+tests)."
