# Makefile for Hippique Orchestrator Cloud Run

.PHONY: help setup test build deploy scheduler logs clean

# Configuration
-include .env
export

help: ## Show this help message
	@echo "Hippique Orchestrator - Cloud Run"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## Setup GCP infrastructure
	@echo "🔧 Setting up GCP resources..."
	@chmod +x scripts/*.sh
	@./scripts/setup_gcp.sh

test: ## Run local tests
	@echo "🧪 Running local tests..."
	@chmod +x scripts/test_local.sh
	@./scripts/test_local.sh

build: ## Build Docker image locally
	@echo "📦 Building Docker image..."
	@docker build -t hippique-orchestrator:local .

run-local: build ## Run service locally with Docker
	@echo "🚀 Running service locally..."
	@docker run --rm -p 8080:8080 \
		--env-file .env \
		-e REQUIRE_AUTH=false \
		hippique-orchestrator:local

deploy: ## Deploy to Cloud Run
	@echo "☁️  Deploying to Cloud Run..."
	@chmod +x scripts/deploy_cloud_run.sh
	@./scripts/deploy_cloud_run.sh

scheduler: ## Create Cloud Scheduler job
	@echo "📅 Creating scheduler..."
	@chmod +x scripts/create_scheduler_0900.sh
	@./scripts/create_scheduler_0900.sh

# Monitoring commands
logs: ## Tail service logs
	@gcloud logs tail "resource.type=cloud_run_revision AND resource.labels.service_name=$(SERVICE_NAME)" \
		--project=$(PROJECT_ID) --format=json

logs-scheduler: ## View scheduler logs
	@gcloud scheduler jobs logs read hippique-daily-planning \
		--location=$(REGION) --project=$(PROJECT_ID) --limit=50

logs-tasks: ## View tasks queue status
	@gcloud tasks queues describe $(QUEUE_ID) \
		--location=$(QUEUE_LOCATION) --project=$(PROJECT_ID)

# Testing commands
test-health: ## Test health endpoint
	@curl -s $(SERVICE_URL)/healthz | jq

test-schedule: ## Test schedule endpoint
	@curl -s -X POST $(SERVICE_URL)/schedule \
		-H "Authorization: Bearer $$(gcloud auth print-identity-token)" \
		-H "Content-Type: application/json" \
		-d '{"date":"today","mode":"tasks"}' | jq

test-run: ## Test run endpoint (requires COURSE_URL env var)
	@curl -s -X POST $(SERVICE_URL)/run \
		-H "Authorization: Bearer $$(gcloud auth print-identity-token)" \
		-H "Content-Type: application/json" \
		-d '{"course_url":"$(COURSE_URL)","phase":"H30","date":"2025-01-15"}' | jq

# Maintenance commands
pause-scheduler: ## Pause daily scheduler
	@gcloud scheduler jobs pause hippique-daily-planning \
		--location=$(REGION) --project=$(PROJECT_ID)

resume-scheduler: ## Resume daily scheduler
	@gcloud scheduler jobs resume hippique-daily-planning \
		--location=$(REGION) --project=$(PROJECT_ID)

pause-queue: ## Pause tasks queue
	@gcloud tasks queues pause $(QUEUE_ID) \
		--location=$(QUEUE_LOCATION) --project=$(PROJECT_ID)

resume-queue: ## Resume tasks queue
	@gcloud tasks queues resume $(QUEUE_ID) \
		--location=$(QUEUE_LOCATION) --project=$(PROJECT_ID)

purge-queue: ## Purge all tasks from queue (DANGEROUS)
	@echo "⚠️  This will delete all pending tasks!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		gcloud tasks queues purge $(QUEUE_ID) \
			--location=$(QUEUE_LOCATION) --project=$(PROJECT_ID); \
	fi

# GCS commands
gcs-list: ## List GCS artifacts
	@gsutil ls -r gs://$(GCS_BUCKET)/$(GCS_PREFIX)/

gcs-sync: ## Download all artifacts
	@mkdir -p backups/
	@gsutil -m rsync -r gs://$(GCS_BUCKET)/$(GCS_PREFIX)/ backups/

# Development commands
format: ## Format Python code
	@black src/ scripts/
	@echo "✅ Code formatted"

lint: ## Lint Python code
	@flake8 src/ scripts/ --max-line-length=100
	@echo "✅ Linting passed"

# Cleanup
clean: ## Clean local artifacts
	@rm -rf __pycache__ .pytest_cache
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@echo "✅ Cleaned"

destroy: ## Destroy all GCP resources (DANGEROUS)
	@echo "⚠️  This will delete all Cloud Run, Tasks, and Scheduler resources!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		gcloud run services delete $(SERVICE_NAME) --region=$(REGION) --project=$(PROJECT_ID) --quiet || true; \
		gcloud scheduler jobs delete hippique-daily-planning --location=$(REGION) --project=$(PROJECT_ID) --quiet || true; \
		gcloud tasks queues delete $(QUEUE_ID) --location=$(QUEUE_LOCATION) --project=$(PROJECT_ID) --quiet || true; \
		echo "✅ Resources deleted"; \
	fi

