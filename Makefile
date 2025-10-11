<<<<<<< HEAD
.RECIPEPREFIX := >
.PHONY: compile helpcheck importcheck

compile:
> python tools/compile_check.py

helpcheck:
> python tools/ci_check.py --mode helpcheck --timeout 5

importcheck:
> python tools/ci_check.py --mode importcheck --timeout 5

.PHONY: test doctor

test:
> pytest -q || true

doctor: compile helpcheck test
=======
.PHONY: install lint test smoke
install:
	python3 -m venv .venv && . .venv/bin/activate && \
	pip install -U pip wheel && \
	( [ -f requirements.txt ] && pip install -r requirements.txt || true ) && \
	pip install ruff pytest pandas pyyaml beautifulsoup4 lxml openpyxl

lint:
	. .venv/bin/activate && ruff check .

test:
	. .venv/bin/activate && pytest -q || true

smoke: install
	./scripts/cloudshell_verify.sh
>>>>>>> origin/main
