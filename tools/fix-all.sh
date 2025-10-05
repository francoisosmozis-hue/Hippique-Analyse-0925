#!/usr/bin/env bash
set -euo pipefail

echo "== Install tooling =="
python -m pip install -U pip wheel >/dev/null
pip install -q ruff black yamllint pytest

echo "== Normalize tabs -> spaces =="
# Python & Workflows
find . -type f \( -name "*.py" -o -path ".github/workflows/*.yml" -o -path ".github/workflows/*.yaml" \) \
  -print0 | xargs -0 sed -i 's/\t/  /g'

echo "== Python: ruff --fix + black =="
ruff check . --fix || true
black .

echo "== Workflows: yamllint =="
# On ne s'arrête pas en cas d'erreur: on veut lister, puis corriger manuellement si besoin
if ls .github/workflows/*.y*ml >/dev/null 2>&1; then
  yamllint .github/workflows || true
fi

echo "== Detect & suggest fix for 'if: secrets.*' =="
WF_DIR=".github/workflows"
if [ -d "$WF_DIR" ]; then
  MATCHES=$(grep -RniE '^\s*if:\s*(\${{\s*)?secrets\.' "$WF_DIR" || true)
  if [ -n "$MATCHES" ]; then
    echo "!! Found 'if: secrets.*' lines:"
    echo "$MATCHES"
    echo
    echo "Applying conservative rewrite to use env.* (you must review the diff):"
    # Remplacement minimal: secrets.X -> env.X dans if:, à condition que X soit mappé en env dans le job (à ajouter manuellement si absent)
    # On ne touche QUE les if:, on n'insère pas automatiquement le bloc env de job pour éviter un YAML cassé.
    while IFS= read -r f; do
      file="${f%%:*}"
      sed -i -E 's/^([[:space:]]*if:[[:space:]]*\${{\s*)secrets\.([A-Z0-9_]+)(\s*[=!]=\s*'\''?[^}]*\s*'\''?\s*}})/\1env.\2\3/g' "$file"
      sed -i -E 's/^([[:space:]]*if:[[:space:]]*)secrets\.([A-Z0-9_]+)(\s*[=!]=\s*'\''?[^}]*\s*'\''?)/\1\${{ env.\2\3 }}/g' "$file"
    done < <(echo "$MATCHES" | cut -d: -f1 | sort -u)
    echo ">> IMPORTANT: vérifie que chaque job ayant ces conditions possède bien un bloc 'env:' mappant le secret:"
    echo "   env:"
    echo "     GOOGLE_CREDENTIALS_B64: \${{ secrets.GOOGLE_CREDENTIALS_B64 || '' }}"
    echo "     DRIVE_FOLDER_ID: \${{ secrets.DRIVE_FOLDER_ID || '' }}"
  fi
fi

echo "== Quick pytest =="
pytest -q || true

echo "== Done. Review changes =="
git status
git --no-pager diff --color | sed -n '1,200p'
