# TEST_PLAN.md

Ce document détaille les commandes d'exécution des tests et de la validation de l'application `hippique-orchestrator`.

## 1. Exécution des tests locaux (Pytest)

### Description
La suite de tests locale est basée sur `pytest` et utilise des mocks pour assurer la déterministe et l'indépendance aux services externes (Firestore, Cloud Tasks, réseau).

### Commandes
Pour exécuter l'ensemble de la suite de tests et générer le rapport de couverture :

```bash
pytest --cov=. --cov-report=xml:coverage.xml --cov-report=term-missing --ignore=Google-Agent-Development-Kit-Demo
```

**Résultat Attendu:**
-   Tous les tests passent (0 échecs).
-   Un rapport de couverture détaillé est affiché dans la console et un fichier `coverage.xml` est généré.
-   Le rapport `coverage.xml` doit indiquer une couverture globale d'au moins 80% sur les modules critiques (`plan.py`, `firestore_client.py`, `analysis_pipeline.py`).

Pour vérifier l'absence de `flakiness` sur 10 exécutions consécutives :

```bash
FLAKY_RUNS=0
for i in $(seq 1 10); do
    echo "Run $i/10..."
    if ! pytest -q --ignore=Google-Agent-Development-Kit-Demo > "/tmp/pytest_run_$i.log"; then
        echo "pytest failed on run $i" >> "/tmp/flaky_failures.log"
        FLAKY_RUNS=$((FLAKY_RUNS+1))
    fi
done
echo "Finished 10 runs. Total flaky failures: $FLAKY_RUNS"
if [ "$FLAKY_RUNS" -gt 0 ]; then
    echo "Some tests were flaky. Check /tmp/flaky_failures.log for details."
else
    echo "All tests passed consistently over 10 runs."
fi
```

**Résultat Attendu:**
-   `Total flaky failures: 0`.
-   Le message "All tests passed consistently over 10 runs." est affiché.

## 2. Scripts de validation et Smoke Test en production (Complément)

### Description
Ces scripts sont conçus pour effectuer une validation rapide des endpoints clés de l'application déployée en production (ou dans un environnement similaire), sans s'appuyer sur des secrets versionnés.

### Prérequis
-   L'URL de base du service déployé (par exemple, `https://hippique-orchestrator-XXXXX.run.app`).
-   Une clé API interne (`HIPPIQUE_INTERNAL_API_KEY`) configurée dans l'environnement du shell pour les tests d'authentification.

### Commande (scripts/smoke_prod.sh)

```bash
#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
# L'utilisateur doit fournir l'URL du service.
if [ -z "$1" ]; then
    echo "Usage: $0 <SERVICE_URL>"
    echo "Example: $0 https://hippique-orchestrator-XXXXX.run.app"
    exit 1
fi
SERVICE_URL="$1"

# La clé API est lue depuis l'environnement. NE PAS la hardcoder ici.
if [ -z "${HIPPIQUE_INTERNAL_API_KEY}" ]; then
    echo "Error: HIPPIQUE_INTERNAL_API_KEY environment variable is not set."
    exit 1
fi

echo "--- Running smoke tests against $SERVICE_URL ---"

# --- Test /pronostics endpoint ---
echo "Testing /pronostics UI endpoint..."
RESPONSE=$(curl -s "$SERVICE_URL/pronostics")
if echo "$RESPONSE" | grep -q "Hippique Orchestrator - Pronostics"; then
    echo "✅ /pronostics UI is accessible."
else
    echo "❌ /pronostics UI test failed. Response:"
    echo "$RESPONSE"
    exit 1
fi

# --- Test /api/pronostics endpoint ---
echo "Testing /api/pronostics endpoint..."
API_PRONOSTICS_RESPONSE=$(curl -s "$SERVICE_URL/api/pronostics?date=$(date +%F)")
if echo "$API_PRONOSTICS_RESPONSE" | jq . > /dev/null; then
    echo "✅ /api/pronostics returned valid JSON."
else
    echo "❌ /api/pronostics test failed. Response:"
    echo "$API_PRONOSTICS_RESPONSE"
    exit 1
fi

# --- Test /schedule endpoint (without API key - expected 403) ---
echo "Testing /schedule endpoint without API key (expecting 403 Forbidden)..."
SCHEDULE_NO_KEY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/schedule" -X POST -H "Content-Type: application/json" -d '{"dry_run": true}')
if [ "$SCHEDULE_NO_KEY_STATUS" -eq 403 ]; then
    echo "✅ /schedule without API key returned 403 Forbidden as expected."
else
    echo "❌ /schedule without API key failed. Expected 403, got $SCHEDULE_NO_KEY_STATUS."
    exit 1
fi

# --- Test /schedule endpoint (with valid API key - expected 200) ---
echo "Testing /schedule endpoint with valid API key (expecting 200 OK)..."
SCHEDULE_WITH_KEY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/schedule" -X POST -H "Content-Type: application/json" -H "X-API-KEY: ${HIPPIQUE_INTERNAL_API_KEY}" -d '{"dry_run": true, "date": "$(date +%F)"}')
if [ "$SCHEDULE_WITH_KEY_STATUS" -eq 200 ]; then
    echo "✅ /schedule with valid API key returned 200 OK as expected."
else
    echo "❌ /schedule with valid API key failed. Expected 200, got $SCHEDULE_WITH_KEY_STATUS."
    exit 1
fi

echo "--- All smoke tests passed successfully! ---"
```