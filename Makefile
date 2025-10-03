VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

.PHONY: venv test run-h30 run-h5

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	touch $@

venv: $(VENV)/.installed
	@echo "Virtual environment ready at $(VENV)"

test: venv
	$(PYTEST)

run-h30: venv
	@test -n "$(REUNION)" || (echo "REUNION environment variable is required" >&2; exit 1)
	@test -n "$(COURSE)" || (echo "COURSE environment variable is required" >&2; exit 1)
	$(PYTHON) scripts/runner_chain.py --reunion $(REUNION) --course $(COURSE) --phase H30 --ttl-hours ${TTL_HOURS}

run-h5: venv
	@test -n "$(REUNION)" || (echo "REUNION environment variable is required" >&2; exit 1)
	@test -n "$(COURSE)" || (echo "COURSE environment variable is required" >&2; exit 1)
	$(PYTHON) scripts/runner_chain.py --reunion $(REUNION) --course $(COURSE) --phase H5 --budget ${BUDGET} --calibration ${CALIBRATION}

TTL_HOURS ?= 6
BUDGET ?= 5
CALIBRATION ?= calibration/payout_calibration.yaml
