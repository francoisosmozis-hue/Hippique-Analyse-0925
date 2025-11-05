#!/usr/bin/env bash
set -euo pipefail

# ---------------------------- config par défaut -----------------------------
TZ="${TZ:-Europe/Paris}"
REUNION="${REUNION:-R1}"
COURSE="${COURSE:-C1}"
PHASE="${PHASE:-H5}"
BUDGET="${BUDGET:-5}"

PYTHON="${PYTHON:-python}"
RUNNER="${RUNNER:-runner_chain.py}"
ANALYSIS_DIR="${ANALYSIS_DIR:-data/${REUNION}${COURSE}}"
ANALYSIS_FILE="${ANALYSIS_FILE:-${ANALYSIS_DIR}/analysis_${PHASE}.json}"
SNAPSHOT_FILE="${SNAPSHOT_FILE:-${ANALYSIS_DIR}/snapshot_${PHASE}.json}"

# ------------------------------- mise en forme ------------------------------
RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BLUE=$'\e[34m'; NC=$'\e[0m'
info () { echo "${BLUE}ℹ${NC} $*"; }
ok   () { echo "${GREEN}✔${NC} $*"; }
warn () { echo "${YELLOW}⚠${NC} $*"; }
err  () { echo "${RED}✖${NC} $*"; }

cd "$(dirname "$0")/.."  # racine projet

# ------------------------------ pré-checks ---------------------------------
export TZ
info "Python version:"
$PYTHON -V

# normalisation indentation pour éviter les IndentationError
if [ -f runner_chain.py ]; then
  info "Normalisation indentation (tabs -> espaces) sur runner_chain.py"
  expand -t 4 runner_chain.py > runner_chain.fixed && mv runner_chain.fixed runner_chain.py
fi

info "Vérification d'import des modules clés…"
$PYTHON - <<'PY'
mods = ["runner_chain","pipeline_run","online_fetch_zeturf","simulate_ev",
        "p_finale_export","simulate_wrapper","validator_ev","module_dutching_pmu"]
bad=0
import importlib
for m in mods:
    try:
        importlib.import_module(m)
        print("OK import", m)
    except Exception as e:
        print("FAIL import", m, "->", e)
        bad+=1
if bad: raise SystemExit(1)
PY
ok "Imports OK"

info "Compilation syntaxique runner_chain.py"
$PYTHON -m py_compile runner_chain.py
ok "Syntaxe OK"

# ------------------------------ exécution H5 --------------------------------
info "Lancement runner_chain (REUNION=${REUNION}, COURSE=${COURSE}, PHASE=${PHASE}, BUDGET=${BUDGET})"
set +e
OUT=$($PYTHON "$RUNNER" --reunion "$REUNION" --course "$COURSE" --phase "$PHASE" --budget "$BUDGET" 2>&1)
RC=$?
set -e

if [ $RC -ne 0 ]; then
  err "runner_chain a échoué (code $RC). Logs :"
  echo "$OUT"
  exit $RC
fi
ok "runner_chain terminé"

# ------------------------------ artefacts -----------------------------------
info "Vérification des artefacts produits"
ls -l "${ANALYSIS_DIR}" || true

if [ ! -f "$ANALYSIS_FILE" ]; then
  err "Fichier d'analyse introuvable : ${ANALYSIS_FILE}"
  echo "$OUT"
  exit 2
fi

# ----------------------------- lecture EV/ROI -------------------------------
info "Lecture ${ANALYSIS_FILE}"
$PYTHON - <<PY
import json, sys
p = "${ANALYSIS_FILE}"
j = json.load(open(p, "r", encoding="utf-8"))
status = j.get("status") or ("aborted" if j.get("abstain") else "ok")
ev = j.get("ev") or {}
tickets = j.get("tickets") or []
print("STATUS:", status)
print("EV_GLOBAL:", ev.get("global"))
print("ROI_GLOBAL:", ev.get("roi"))
print("NB_TICKETS:", len(tickets))
# résumés tickets SP (si dispo)
for t in tickets:
    num = t.get("num") or t.get("horse") or t.get("label")
    mise = t.get("Stake (€)") or t.get("mise")
    odds = t.get("odds_place") or t.get("cote") or t.get("odds")
    print(" - ticket:", num, "mise=", mise, "odds=", odds)
# signal de sortie
ok = (status == "ok")
print("RESULT_OK:", ok)
PY

ok "Test pipeline terminé"
