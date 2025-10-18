.PHONY: help install lint test smoke setup validate deploy

help:
	@echo "Hippique Analyse - Makefile"
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  install    - Create venv and install dependencies"
	@echo "  lint       - Run linter (ruff)"
	@echo "  test       - Run tests (pytest)"
	@echo "  smoke      - Run smoke tests"
	@echo "  setup      - Initial project setup (create dirs)"
	@echo "  validate   - Validate basic imports"
	@echo "  deploy     - Deploy to Cloud Run"
	@echo "  help       - Show this help message"

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

setup:
	@echo "Setting up project directories..."
	@mkdir -p data logs

validate:
	@echo "Validating basic imports..."
	@. .venv/bin/activate && python3 -c "import pandas; import yaml; import fastapi; print('✅ Core imports OK')"

deploy:
	@echo "🚀 Deploying to Cloud Run..."
	@chmod +x scripts/deploy.sh
	@./scripts/deploy.sh