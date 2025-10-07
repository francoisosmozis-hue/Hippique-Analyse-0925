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
