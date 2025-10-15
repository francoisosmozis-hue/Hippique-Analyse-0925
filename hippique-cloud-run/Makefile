.PHONY: help install test lint format docker-build deploy clean

help:
	 @echo "Available commands:"
	 @echo "  make install       - Install dependencies"
	 @echo "  make test          - Run tests"
	 @echo "  make lint          - Run linters"
	 @echo "  make format        - Format code"
	 @echo "  make docker-build  - Build Docker image"
	 @echo "  make deploy        - Deploy to Cloud Run"
	 @echo "  make clean         - Clean temporary files"

install:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

test:
	pytest tests/ -v --cov=src --cov-report=html

lint:
	flake8 src/ tests/
	mypy src/

format:
	black src/ tests/
	isort src/ tests/

docker-build:
	docker build -t hippique-analyzer:latest .

deploy:
	./scripts/deploy_cloud_run.sh

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov/
