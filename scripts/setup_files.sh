#!/bin/bash
# Script de setup automatique - Hippique Orchestrator

echo "🚀 Création de tous les fichiers..."

# 1. src/__init__.py
cat > src/__init__.py << 'EOF'
"""
Hippique Orchestrator v2.0
"""
__version__ = "2.0.0"
__author__ = "Hippique Team"
EOF

# 2. requirements.txt
cat > requirements.txt << 'EOF'
# FastAPI & ASGI
fastapi==0.104.1
uvicorn[standard]==0.24.0
gunicorn==21.2.0
pydantic==2.5.0

# Google Cloud
google-cloud-tasks==2.15.0
google-cloud-scheduler==2.12.0
google-cloud-storage==2.10.0
google-cloud-logging==3.8.0
protobuf==4.25.1

# HTTP & Async
aiohttp==3.9.1
requests==2.31.0
urllib3==2.1.0

# HTML Parsing
beautifulsoup4==4.12.2
lxml==4.9.3

# Data Processing
pandas==2.1.3
numpy==1.26.2
openpyxl==3.1.2

# Date/Time
python-dateutil==2.8.2
pytz==2023.3
tzdata==2023.3

# Configuration
python-dotenv==1.0.0

# Testing
pytest==7.4.3
pytest-asyncio==0.21.1
pytest-mock==3.12.0

# Utilities
pyyaml==6.0.1
EOF

# 3. .env.example
cat > .env.example << 'EOF'
# GCP Configuration
PROJECT_ID=your-project-id
REGION=europe-west1
SERVICE_NAME=hippique-orchestrator
SERVICE_URL=https://hippique-orchestrator-xxxx-ew.a.run.app
SERVICE_ACCOUNT_EMAIL=hippique-orchestrator@your-project-id.iam.gserviceaccount.com
QUEUE_ID=hippique-tasks

# Timezone
TZ=Europe/Paris

# Security
REQUIRE_AUTH=true

# HTTP Configuration
USER_AGENT=Mozilla/5.0 (Hippique-Orchestrator/2.0)
REQUESTS_PER_SECOND=1.0
TIMEOUT_SECONDS=600

# GCS (Optional)
GCS_BUCKET=
GCS_PREFIX=prod/snapshots

# GPI
BUDGET_PER_RACE=5.0

# Environment
ENVIRONMENT=production
GUNICORN_WORKERS=2
GUNICORN_TIMEOUT=600
LOG_LEVEL=info
EOF

# 4. .gitignore
cat > .gitignore << 'EOF'
__pycache__/
*.py[cod]
.Python
venv/
.env
data/
logs/
*.json
*.csv
*.xlsx
.pytest_cache/
EOF

# 5. Makefile
cat > Makefile << 'EOF'
.PHONY: help setup install validate deploy

help:
	@echo "Hippique Orchestrator - Makefile"
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  setup      - Initial setup"
	@echo "  install    - Install dependencies"
	@echo "  validate   - Validate setup"
	@echo "  deploy     - Deploy to Cloud Run"

setup:
	@echo "Setting up project..."
	@mkdir -p modules calibration config data logs
	@cp .env.example .env 2>/dev/null || true
	@chmod +x scripts/*.sh

install:
	@echo "Installing dependencies..."
	@pip install -r requirements.txt

validate:
	@echo "Validating setup..."
	@python3 -c "from src import config, logging_utils, time_utils; print('✅ Imports OK')"

deploy:
	@./scripts/deploy_cloud_run.sh
EOF

echo "✅ Fichiers de base créés"
echo ""
echo "📝 IMPORTANT: Les fichiers Python principaux (service.py, plan.py, etc.)"
echo "   doivent être copiés depuis les artefacts Claude"
echo ""
echo "Prochaine étape: Copier le contenu des artefacts dans les fichiers"

