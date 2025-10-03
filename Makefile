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

CALIB_PATH ?=
CALIBRATION ?=
BUDGET ?= 5

ifdef CALIB_PATH
RUN_ENV := CALIB_PATH=$(CALIB_PATH) 
else ifdef CALIBRATION
RUN_ENV := CALIB_PATH=$(CALIBRATION) 
else
RUN_ENV :=
endif

run-h30: venv
	@test -n "$(URL)" || (echo "URL variable is required" >&2; exit 1)
	$(RUN_ENV)$(PYTHON) analyse_courses_du_jour_enrichie.py --course-url "$(URL)" --phase H30 --budget $(BUDGET)

run-h5: venv
	@test -n "$(URL)" || (echo "URL variable is required" >&2; exit 1)
	$(RUN_ENV)$(PYTHON) analyse_courses_du_jour_enrichie.py --course-url "$(URL)" --phase H5 --budget $(BUDGET)
