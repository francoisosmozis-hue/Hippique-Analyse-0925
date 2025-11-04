#!/usr/bin/env bash
set -euo pipefail

# ───────────────────────────── Configuration ────────────────────────────────
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
SERVICE="${SERVICE:-service:app}"
PYTHON="${PYTHON:-python}"
CURL="${CURL:-curl}"
TMPLOG="/tmp/uvicorn_smoke.log"

BLUE=$'\e[34m'; GREEN=$'\e[32m'; RED=$'\e[31m'; YELLOW=$'\e[33m'; NC=$'\e[0m'
info(){ echo "${BLUE}ℹ${NC} $*"; }
ok(){ echo "${GREEN}✔${NC} $*"; }
warn(){ echo "${YELLOW}⚠${NC} $*"; }
err(){ echo "${RED}✖${NC} $*"; }

# ───────────────────────────── Lancement serveur ────────────────────────────
info "Démarrage Uvicorn (${SERVICE}) sur port ${PORT}..."
nohup $PYTHON -m uvicorn "$SERVICE" --host "$HOST" --port "$PORT" >"$TMPLOG" 2>&1 &
PID=$!
sleep 2

if ! ps -p "$PID" >/dev/null 2>&1; then
  err "Le serveur n’a pas démarré (voir $TMPLOG)"
  exit 1
fi
ok "Serveur lancé (PID $PID)"

# ───────────────────────────── Tests des endpoints ──────────────────────────
BASE="http://localhost:${PORT}"

test_endpoint () {
  local url="$1"
  local data="${2:-}"
  local method="${3:-GET}"

  echo -n "${BLUE}→${NC} Test ${url} ... "
  if [ "$method" = "POST" ]; then
    res=$($CURL -s -X POST "$BASE$url" -H "content-type: application/json" -d "$data" || true)
  else
    res=$($CURL -s "$BASE$url" || true)
  fi

  if [[ "$res" == *"ok"* || "$res" == *"status"* || "$res" == *"versions"* ]]; then
    echo "${GREEN}OK${NC}"
    echo "$res" | jq . || echo "$res"
  else
    echo "${RED}FAIL${NC}"
    echo "$res"
  fi
}

info "Ping santé /__health"
test_endpoint "/__health"

info "Test /prompt/generate"
test_endpoint "/prompt/generate" '{"reunion":"R1","course":"C1","budget":5}' POST

info "Test /pipeline/run"
test_endpoint "/pipeline/run" '{"reunion":"R1","course":"C1","phase":"H5","budget":5}' POST

# ───────────────────────────── Nettoyage ────────────────────────────────────
info "Arrêt du serveur (PID $PID)"
kill "$PID" >/dev/null 2>&1 || true
sleep 1
ok "Serveur arrêté proprement"

# ───────────────────────────── Résumé ───────────────────────────────────────
echo
ok "Smoke test API terminé."
echo "Logs Uvicorn disponibles dans : $TMPLOG"
