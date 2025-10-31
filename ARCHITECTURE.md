# Hippique Orchestrator - Cloud Run Architecture

## Structure du projet

```
hippique-orchestrator/
├── .env.example
├── .dockerignore
├── .gitignore
├── Dockerfile
├── gunicorn.conf.py
├── requirements.txt
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── service.py           # FastAPI service principal
│   ├── plan.py              # Construction plan du jour
│   ├── scheduler.py         # Programmation Cloud Tasks/Scheduler
│   ├── runner.py            # Orchestrateur d'analyse GPI
│   ├── config.py            # Configuration & env vars
│   ├── logging_utils.py     # Logs structurés JSON
│   ├── time_utils.py        # Gestion timezone Europe/Paris
│   └── exceptions.py        # Exceptions personnalisées
│
├── scripts/
│   ├── deploy_cloud_run.sh
│   └── create_scheduler_0900.sh
│
├── tests/
│   ├── __init__.py
│   ├── test_plan.py
│   ├── test_scheduler.py
│   └── fixtures/
│       ├── zeturf_program.html
│       └── geny_schedule.html
│
└── modules/                 # Modules GPI v5.1 existants
    ├── analyse_courses_du_jour_enrichie.py
    ├── online_fetch_zeturf.py
    ├── fetch_je_stats.py
    ├── fetch_je_chrono.py
    ├── p_finale_export.py
    ├── simulate_ev.py
    ├── pipeline_run.py
    ├── update_excel_with_results.py
    └── get_arrivee_geny.py
```

## Fichiers de configuration

### .env.example
```env
# GCP Configuration
PROJECT_ID=your-gcp-project-id
REGION=europe-west1
SERVICE_NAME=hippique-orchestrator
QUEUE_ID=hippique-tasks
SERVICE_ACCOUNT_EMAIL=hippique-sa@your-project.iam.gserviceaccount.com

# Timezone
TZ=Europe/Paris

# Storage
GCS_BUCKET=hippique-data
GCS_PREFIX=prod

# Security
REQUIRE_AUTH=true
OIDC_AUDIENCE=https://hippique-orchestrator-xxx.run.app

# Application
LOG_LEVEL=INFO
MAX_RETRIES=3
TIMEOUT_SECONDS=600

# Rate limiting
REQUESTS_PER_SECOND=1
USER_AGENT=HippiqueAnalyzer/5.1 (+contact@yourdomain.com)

# GPI v5.1 Settings
BUDGET_TOTAL=5.0
SP_RATIO=0.6
COMBO_RATIO=0.4
EV_MIN_GLOBAL=0.40
ROI_MIN_GLOBAL=0.25
```

### .gitignore
```
