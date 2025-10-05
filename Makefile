# ====== Makefile — Pipeline PMU "gratuit" (turfinfo) ======
SHELL := /bin/bash
TZ := Europe/Paris

# Dossier de sortie & date (par défaut: aujourd'hui, heure Paris)
OUT ?= data/pmu
DATE ?= $(shell TZ=$(TZ) date +%F)

# Python (venv)
PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help venv install tree fetch odds h30 h5 clean

help:
	@echo "Cibles principales:"
	@echo "  make fetch           # programme + participants + rapports (toutes courses FR)"
	@echo "  make odds            # odds H-30 puis H-5 -> CSV"
	@echo "  make h30             # seulement odds H-30"
	@echo "  make h5              # seulement odds H-5"
	@echo "Variables:"
	@echo "  DATE=YYYY-MM-DD (def: aujourd'hui Paris)   OUT=chemin (def: data/pmu)"

venv:
	python3 -m venv .venv
	$(PIP) install -U pip wheel
	# Si tu as un requirements.txt, dé-commente la ligne suivante :
	# $(PIP) install -r requirements.txt
	# Dépendances minimales
	$(PIP) install requests

install: venv
	@echo "Dépendances installées."

tree:
	@echo "Sortie: $(OUT)/$(DATE)"
	@mkdir -p "$(OUT)/$(DATE)"
	@find "$(OUT)/$(DATE)" -maxdepth 3 -type f 2>/dev/null || true

# --- Fetch global (programme + participants + rapports) ---
fetch: install
	$(PY) scripts/pmu_fetch.py --date "$(DATE)" --out "$(OUT)" || true
	@$(MAKE) tree

# --- Odds snapshots ---
h30: install
	$(PY) scripts/pmu_odds.py --date "$(DATE)" --out "$(OUT)" --tag h30 || true
	@ls -l "$(OUT)/$(DATE)/odds_h30.csv"

h5: install
	$(PY) scripts/pmu_odds.py --date "$(DATE)" --out "$(OUT)" --tag h5 || true
	@ls -l "$(OUT)/$(DATE)/odds_h5.csv"

odds: h30 h5
	@echo "[✓] Snapshots odds terminés: $(OUT)/$(DATE)/odds_h30.csv & odds_h5.csv"

clean:
	rm -rf .venv __pycache__