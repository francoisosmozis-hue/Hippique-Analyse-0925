#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/work/Hippique-Analyse-0925-sweep}"
REPO_SLUG="${REPO_SLUG:-francoisosmozis-hue/Hippique-Analyse-0925}"

echo ">> Reprise GitHub + Gemini pour $REPO_SLUG"

# 1) Vérif/refresh auth GitHub
if ! gh auth status >/dev/null 2>&1; then
  echo ">> Auth GitHub absente. Ouvre la page web de login…"
  gh auth login -s "repo,workflow,user:email" --web
fi

# 2) Export du token pour l'écosystème (Gemini/MCP)
export GITHUB_TOKEN="$(gh auth token)"
export GITHUB_REPOSITORY="${REPO_SLUG}"

# 3) Petits réglages git (sécurisés, idempotents)
git config --global init.defaultBranch main
git config --global pull.rebase false
gh auth setup-git || true

# 4) Aller dans le dépôt
cd "$REPO_DIR"

# 5) Vérifs rapides
git remote -v || true
gh repo view "$REPO_SLUG" >/dev/null || gh repo view --web

echo ">> OK. Lance 'gemini' dans $REPO_DIR pour travailler."
