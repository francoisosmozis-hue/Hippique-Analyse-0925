# 🏇 Hippique Orchestrator v2.0

**Cloud Run orchestrator for automated horse racing analysis (GPI v5.1)**

Automated daily planning and execution of horse racing analyses with:
- ⏰ **Daily scheduling** at 09:00 (Europe/Paris)
- 📊 **H-30 snapshots** (30 minutes before each race)
- 🎯 **H-5 analysis** (5 minutes before each race) with ticket generation
- ☁️ **Fully serverless** on Google Cloud Platform
- 🔐 **Secure** with OIDC authentication
- 📈 **Observable** with structured logging

---

## 🏗️ Architecture

```
Cloud Scheduler (09:00 Paris)
    ↓
POST /schedule → Cloud Run Service
    ↓
    ├─ Build daily plan (Geny + ZEturf)
    └─ Create ~80 Cloud Tasks (H-30 + H-5)
        ↓
        Cloud Tasks Queue
        ↓
        POST /run → Execute GPI analysis
        ↓
        Optional: Upload artifacts to GCS
```

### Components

| Component | Role | Technology |
|-----------|------|------------|
| **Cloud Run** | HTTP service with 3 endpoints | FastAPI + Gunicorn |
| **Cloud Scheduler** | Daily trigger at 09:00 | Cron job |
| **Cloud Tasks** | H-30/H-5 execution queue | Async task queue |
| **GCS** (optional) | Artifact storage | Google Cloud Storage |
| **Modules GPI** | Racing analysis logic | Python subprocess |

---

## 📦 Project Structure

```
hippique-orchestrator/
├── src/
│   ├── service.py          # FastAPI service (3 endpoints)
│   ├── plan.py             # Daily plan builder (Geny + ZEturf)
│   ├── scheduler.py        # Cloud Tasks scheduler
│   ├── runner.py           # GPI modules orchestrator
│   ├── config.py           # Configuration loader
│   ├── logging_utils.py    # Structured JSON logging
│   └── time_utils.py       # Timezone utilities (Europe/Paris)
├── modules/                # GPI v5.1 modules (existing)
│   ├── discover_geny_today.py
│   ├── online_fetch_zeturf.py
│   ├── analyse_courses_du_jour_enrichie.py
│   └── ...
├── scripts/
│   ├── deploy_cloud_run.sh
│   └── create_scheduler_0900.sh
├── Dockerfile
├── gunicorn.conf.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 Quick Start

### Prerequisites

- **GCP Project** with billing enabled
- **gcloud CLI** installed and configured
- **Docker** (optional, for local testing)
- **Python 3.11+** (for local development)

### 1. Clone and Configure

```bash
# Clone repository
git clone <your-repo>
cd hippique-orchestrator

# Copy environment template
cp .env.example .env

# Edit .env with your GCP project details
nano .env
```

**Required variables in `.env`:**
```bash
PROJECT_ID=your-project-id
REGION=europe-west1
SERVICE_NAME=hippique-orchestrator
```

### 2. Deploy to Cloud Run

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Deploy service
./scripts/deploy_cloud_run.sh
```

This script will:
- ✅ Enable required GCP APIs
- ✅ Create service account with IAM roles
- ✅ Build and push Docker image
- ✅ Create Cloud Tasks queue
- ✅ Deploy Cloud Run service
- ✅ Configure OIDC authentication

**Copy the SERVICE_URL** from the output and update your `.env`:
```bash
SERVICE_URL=https://hippique-orchestrator-xxxx-ew.a.run.app
```

### 3. Create Daily Scheduler

```bash
# Create Cloud Scheduler job (09:00 daily)
./scripts/create_scheduler_0900.sh
```

This creates a cron job that calls `POST /schedule` every day at 09:00 (Europe/Paris).

### 4. Verify Deployment

```bash
# Test health endpoint (no auth required)
curl https://your-service-url/healthz

# Test schedule endpoint (requires auth)
curl -X POST https://your-service-url/schedule \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"date":"today","mode":"tasks"}'
```

---

## 🔌 API Endpoints

### `GET /healthz`

Health check endpoint (no authentication required).

**Response:**
```json
{
  "status": "healthy",
  "service": "hippique-orchestrator",
  "version": "2.0.0",
  "timestamp": "2025-10-16T08:30:00Z"
}
```

### `POST /schedule`

Generate daily plan and schedule H-30/H-5 analyses.

**Request:**
```json
{
  "date": "2025-10-16",  // or "today"
  "mode": "tasks"         // "tasks" or "scheduler"
}
```

**Response:**
```json
{
  "ok": true,
  "date": "2025-10-16",
  "total_races": 40,
  "scheduled_h30": 38,
  "scheduled_h5": 38,
  "mode": "tasks",
  "plan_summary": [
    {
      "race": "R1C3",
      "time": "14:30",
      "meeting": "Paris-Vincennes (FR)",
      "url": "https://www.zeturf.fr/fr/course/2025-10-16/R1C3"
    }
  ],
  "correlation_id": "..."
}
```

### `POST /run`

Execute analysis for one race (called by Cloud Tasks).

**Request:**
```json
{
  "course_url": "https://www.zeturf.fr/fr/course/2025-10-16/R1C3-...",
  "phase": "H30",  // "H30" or "H5"
  "date": "2025-10-16"
}
```

**Response:**
```json
{
  "ok": true,
  "phase": "H30",
  "returncode": 0,
  "stdout_tail": "...",
  "artifacts": [
    "data/R1C3/snapshot_h30.json",
    "data/R1C3/cotes.csv"
  ],
  "correlation_id": "..."
}
```

---

## 🔐 Security

### OIDC Authentication

All endpoints except `/healthz` require OIDC token authentication:

```bash
# Get OIDC token
TOKEN=$(gcloud auth print-identity-token)

# Call authenticated endpoint
curl -X POST https://your-service-url/schedule \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"date":"today"}'
```

### IAM Roles

The service account needs:
- `roles/run.invoker` - Invoke Cloud Run service
- `roles/cloudtasks.enqueuer` - Create Cloud Tasks
- `roles/storage.objectAdmin` - Upload to GCS (optional)

---

## 📊 Monitoring

### View Logs

```bash
# Stream Cloud Run logs
gcloud run services logs tail hippique-orchestrator \
  --region=europe-west1

# View specific correlation ID
gcloud logging read 'jsonPayload.correlation_id="run-20251016-r1c3-h30"' \
  --limit=50 --format=json
```

### View Scheduled Tasks

```bash
# List pending tasks
gcloud tasks queues describe hippique-tasks \
  --location=europe-west1

# List all tasks
gcloud tasks list --queue=hippique-tasks \
  --location=europe-west1
```

### View Scheduler Jobs

```bash
# View job details
gcloud scheduler jobs describe hippique-daily-planning \
  --location=europe-west1

# View execution logs
gcloud scheduler jobs logs read hippique-daily-planning \
  --location=europe-west1 --limit=20
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROJECT_ID` | ✅ | - | GCP project ID |
| `REGION` | ❌ | `europe-west1` | GCP region |
| `SERVICE_NAME` | ❌ | `hippique-orchestrator` | Cloud Run service name |
| `SERVICE_URL` | ✅ | - | Cloud Run service URL |
| `SERVICE_ACCOUNT_EMAIL` | ✅ | (auto) | Service account email |
| `QUEUE_ID` | ❌ | `hippique-tasks` | Cloud Tasks queue ID |
| `TZ` | ❌ | `Europe/Paris` | Timezone for race times |
| `REQUIRE_AUTH` | ❌ | `true` | Enable OIDC authentication |
| `REQUESTS_PER_SECOND` | ❌ | `1.0` | HTTP rate limit |
| `TIMEOUT_SECONDS` | ❌ | `600` | Subprocess timeout |
| `GCS_BUCKET` | ❌ | - | GCS bucket for artifacts |
| `GCS_PREFIX` | ❌ | `prod/snapshots` | GCS path prefix |
| `BUDGET_PER_RACE` | ❌ | `5.0` | Budget per race (euros) |

### Rate Limiting

The service implements global rate limiting:
- **1 request/second** per host by default
- Configurable via `REQUESTS_PER_SECOND`
- Shared lock between all async tasks

---

## 🧪 Testing

### Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment
export PROJECT_ID=your-project
export SERVICE_URL=http://localhost:8080
export REQUIRE_AUTH=false

# Run locally
uvicorn src.service:app --host 0.0.0.0 --port 8080
```

### Docker Testing

```bash
# Build image
docker build -t hippique-orchestrator:local .

# Run container
docker run --rm -p 8080:8080 \
  --env-file .env \
  -e REQUIRE_AUTH=false \
  hippique-orchestrator:local

# Test endpoints
curl http://localhost:8080/healthz
```

---

## 🛠️ Maintenance

### Pause Daily Scheduling

```bash
# Pause scheduler
gcloud scheduler jobs pause hippique-daily-planning \
  --location=europe-west1

# Resume scheduler
gcloud scheduler jobs resume hippique-daily-planning \
  --location=europe-west1
```

### Pause Task Queue

```bash
# Pause queue (prevent task execution)
gcloud tasks queues pause hippique-tasks \
  --location=europe-west1

# Resume queue
gcloud tasks queues resume hippique-tasks \
  --location=europe-west1
```

### Update Service

```bash
# Redeploy with latest code
./scripts/deploy_cloud_run.sh
```

---

## 🐛 Troubleshooting

### Issue: "SERVICE_URL not found"

**Solution:** Run `deploy_cloud_run.sh` first, then copy the SERVICE_URL to your `.env` file.

### Issue: "OIDC token invalid"

**Solution:** Generate a fresh token:
```bash
gcloud auth print-identity-token
```

### Issue: "Cloud Tasks not executing"

**Diagnosis:**
```bash
# Check queue status
gcloud tasks queues describe hippique-tasks --location=europe-west1

# Check if queue is paused
# Look for "state: PAUSED"
```

**Solution:**
```bash
# Resume queue if paused
gcloud tasks queues resume hippique-tasks --location=europe-west1
```

### Issue: "Rate limit exceeded"

**Solution:** Increase `REQUESTS_PER_SECOND` in `.env` and redeploy:
```bash
REQUESTS_PER_SECOND=2.0
./scripts/deploy_cloud_run.sh
```

---

## 📝 Changelog

### v2.0.0 (October 2025)

**Major refactoring with 5 critical bug fixes:**

1. ⚡ **Performance**: 40s → 8s (asyncio + aiohttp parallelization)
2. 🔄 **Duplication**: -80 lines (import from `online_fetch_zeturf`)
3. 💥 **CLI args**: Fixed `--course-url` (was using non-existent `--course-id`)
4. 🔴 **Asyncio**: Fixed RuntimeError in FastAPI (use `build_plan_async()`)
5. 🚦 **Rate limiter**: Fixed global lock (was 40 req/s, now respects 1 req/s)

**New features:**
- FastAPI with structured logging
- Cloud Tasks idempotence (deterministic task names)
- Optional GCS artifact storage
- Comprehensive error handling

---

## 📄 License

Proprietary - All rights reserved

---

## 👥 Support

For issues or questions:
1. Check logs: `gcloud run services logs tail hippique-orchestrator`
2. Review documentation: This README
3. Contact: [your-email]

---

**Built with ❤️ for professional horse racing analysis**
