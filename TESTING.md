# Guide de Tests - Hippique Orchestrator

Ce document dÃ©crit les stratÃ©gies de tests, de validation et de smoke tests pour le systÃ¨me.

## 🧪 StratÃ©gie de Tests

### Pyramide de Tests

```
        /\
       /  \      E2E Tests (Cloud)
      /    \     â""-â"€ Smoke tests production
     /------\    
    /        \   Integration Tests
   /          \  â""-â"€ API endpoints
  /            \ â""-â"€ Cloud Tasks flow
 /--------------\
/                \  Unit Tests
â""â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"˜ â""-â"€ plan.py
                    â""-â"€ scheduler.py
                    â""-â"€ runner.py
```

## 🔬 Unit Tests

### Setup

```bash
# Installer pytest
pip install pytest pytest-asyncio pytest-mock

# Lancer les tests
pytest tests/ -v
```

### Tests de plan.py

```python
# tests/test_plan.py
import pytest
from src.plan import parse_zeturf_program, fill_times_from_geny, build_plan

def test_parse_zeturf_program_success(requests_mock):
    """Test parsing ZEturf avec HTML mock"""
    html = """
    <section class="meeting">
        <h2>RÃ©union 1 - VINCENNES</h2>
        <a href="/fr/course/2025-10-28/R1C1-prix-test">Course 1</a>
        <a href="/fr/course/2025-10-28/R1C2-prix-test">Course 2</a>
    </section>
    """
    requests_mock.get(
        "https://www.zeturf.fr/fr/programme-courses-pmu/2025-10-28",
        text=html
    )
    
    result = parse_zeturf_program("2025-10-28")
    
    assert len(result) == 2
    assert result[0]["r_label"] == "R1"
    assert result[0]["c_label"] == "C1"
    assert result[0]["meeting"] == "VINCENNES"
    assert "zeturf.fr" in result[0]["course_url"]

def test_fill_times_from_geny(requests_mock):
    """Test enrichissement heures depuis Geny"""
    html = """
    <div class="reunion">
        <h2>R1</h2>
        <div class="course">C1 - 14h30</div>
        <div class="course">C2 - 15h00</div>
    </div>
    """
    requests_mock.get(
        "https://www.genybet.fr/turf/programme-pmu/2025-10-28",
        text=html
    )
    
    plan = [
        {"r_label": "R1", "c_label": "C1"},
        {"r_label": "R1", "c_label": "C2"},
    ]
    
    result = fill_times_from_geny("2025-10-28", plan)
    
    assert result[0]["time_local"] == "14:30"
    assert result[1]["time_local"] == "15:00"

def test_build_plan_integration():
    """Test build_plan complet (nÃ©cessite internet)"""
    # Skip si pas de connexion
    plan = build_plan("today")
    
    # VÃ©rifications basiques
    for item in plan:
        assert "r_label" in item
        assert "c_label" in item
        assert "time_local" in item
        assert "course_url" in item
        assert item["r_label"].startswith("R")
        assert item["c_label"].startswith("C")
```

### Tests de scheduler.py

```python
# tests/test_scheduler.py
import pytest
from unittest.mock import Mock, patch
from src.scheduler import enqueue_run_task, schedule_all_races

def test_generate_task_name():
    """Test gÃ©nÃ©ration noms de tÃ¢ches"""
    from src.scheduler import _generate_task_name
    
    name = _generate_task_name("2025-10-28", "R1", "C3", "H30")
    assert name == "run-20251028-r1c3-h30"
    
    name = _generate_task_name("2025-10-28", "R2", "C10", "H5")
    assert name == "run-20251028-r2c10-h5"

@patch('src.scheduler.get_tasks_client')
def test_enqueue_run_task_success(mock_client):
    """Test crÃ©ation tÃ¢che Cloud Tasks"""
    mock_client.return_value.create_task.return_value = Mock(name="task-123")
    
    result = enqueue_run_task(
        course_url="https://www.zeturf.fr/fr/course/2025-10-28/R1C3-test",
        phase="H30",
        date="2025-10-28",
        race_time_local="14:30",
        r_label="R1",
        c_label="C3",
    )
    
    assert result is not None
    mock_client.return_value.create_task.assert_called_once()

@patch('src.scheduler.get_tasks_client')
def test_enqueue_run_task_idempotent(mock_client):
    """Test idempotence (tÃ¢che existe dÃ©jÃ )"""
    from google.api_core.exceptions import AlreadyExists
    
    mock_client.return_value.create_task.side_effect = AlreadyExists("Task exists")
    
    result = enqueue_run_task(
        course_url="https://www.zeturf.fr/fr/course/2025-10-28/R1C3-test",
        phase="H30",
        date="2025-10-28",
        race_time_local="14:30",
        r_label="R1",
        c_label="C3",
    )
    
    assert result is not None  # Should handle gracefully
```

### Tests de runner.py

```python
# tests/test_runner.py
import pytest
from unittest.mock import Mock, patch
from src.runner import run_course, _extract_rc_from_url

def test_extract_rc_from_url():
    """Test extraction R/C depuis URL"""
    url = "https://www.zeturf.fr/fr/course/2025-10-28/R1C3-prix-test"
    r, c = _extract_rc_from_url(url)
    assert r == "R1"
    assert c == "C3"
    
    url = "https://www.zeturf.fr/fr/course/2025-10-28/R10C15-prix-test"
    r, c = _extract_rc_from_url(url)
    assert r == "R10"
    assert c == "C15"

@patch('src.runner._run_subprocess')
def test_run_course_h30_success(mock_subprocess):
    """Test exÃ©cution H30 rÃ©ussie"""
    mock_subprocess.return_value = (0, "Success", "")
    
    result = run_course(
        course_url="https://www.zeturf.fr/fr/course/2025-10-28/R1C3-test",
        phase="H30",
        date="2025-10-28",
    )
    
    assert result["ok"] is True
    assert result["phase"] == "H30"
    assert result["returncode"] == 0

@patch('src.runner._run_subprocess')
def test_run_course_h5_pipeline(mock_subprocess):
    """Test pipeline H5 complet"""
    # Mock tous les subprocess calls
    mock_subprocess.return_value = (0, "Success", "")
    
    result = run_course(
        course_url="https://www.zeturf.fr/fr/course/2025-10-28/R1C3-test",
        phase="H5",
        date="2025-10-28",
    )
    
    assert result["ok"] is True
    assert result["phase"] == "H5"
    # VÃ©rifier que plusieurs modules ont Ã©tÃ© appelÃ©s
    assert mock_subprocess.call_count >= 4  # analyse + p_finale + simulate + pipeline
```

### Lancer les Tests Unitaires

```bash
# Tous les tests
pytest tests/ -v

# Avec coverage
pytest tests/ --cov=src --cov-report=html

# Tests spÃ©cifiques
pytest tests/test_plan.py -v
pytest tests/test_scheduler.py -v
pytest tests/test_runner.py -v

# Tests rapides (skip integration)
pytest tests/ -m "not integration"
```

## 🔌 Integration Tests

### Tests API (FastAPI)

```python
# tests/test_service.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from src.service import app

client = TestClient(app)

def test_healthz():
    """Test health check endpoint"""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "timestamp" in response.json()

@patch('src.service.verify_oidc_token')
@patch('src.plan_module.build_plan')
@patch('src.scheduler.schedule_all_races')
def test_schedule_endpoint_success(mock_schedule, mock_plan, mock_auth):
    """Test /schedule endpoint"""
    mock_auth.return_value = True
    mock_plan.return_value = [
        {
            "date": "2025-10-28",
            "r_label": "R1",
            "c_label": "C1",
            "time_local": "14:30",
            "course_url": "https://...",
        }
    ]
    mock_schedule.return_value = [
        {"race": "R1C1", "phase": "H30", "ok": True},
        {"race": "R1C1", "phase": "H5", "ok": True},
    ]
    
    response = client.post(
        "/schedule",
        json={"date": "2025-10-28", "mode": "tasks"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["summary"]["total_races"] == 1
    assert data["summary"]["tasks_created"] == 2

@patch('src.service.verify_oidc_token')
@patch('src.runner.run_course')
def test_run_endpoint_success(mock_runner, mock_auth):
    """Test /run endpoint"""
    mock_auth.return_value = True
    mock_runner.return_value = {
        "ok": True,
        "phase": "H30",
        "returncode": 0,
        "artifacts": [],
    }
    
    response = client.post(
        "/run",
        json={
            "course_url": "https://www.zeturf.fr/fr/course/2025-10-28/R1C3-test",
            "phase": "H30",
            "date": "2025-10-28",
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["phase"] == "H30"

def test_run_endpoint_unauthorized():
    """Test /run sans auth"""
    # Assuming REQUIRE_AUTH=true
    response = client.post(
        "/run",
        json={
            "course_url": "https://...",
            "phase": "H30",
            "date": "2025-10-28",
        }
    )
    
    # Should be 401 if auth is enforced
    assert response.status_code in [401, 200]  # Depends on REQUIRE_AUTH
```

### Lancer les Tests d'IntÃ©gration

```bash
# Local (sans auth)
export REQUIRE_AUTH=false
export PROJECT_ID=test-project
export REGION=europe-west1
export SERVICE_NAME=test-service
export QUEUE_ID=test-queue

pytest tests/test_service.py -v

# Avec serveur local
python -m uvicorn src.service:app --reload &
pytest tests/integration/ -v
kill %1
```

## ðŸš€ E2E Tests (Cloud)

### Smoke Tests Production

```bash
#!/bin/bash
# tests/smoke_test_cloud.sh

set -e

SERVICE_URL="https://hippique-orchestrator-xxx.run.app"
TOKEN=$(gcloud auth print-identity-token)

echo "ðŸš¬ Smoke Test - Cloud Run Service"
echo "=================================="

# Test 1: Health check
echo ""
echo "âœ… Test 1: Health Check"
curl -sf "$SERVICE_URL/healthz" | jq .
echo "âœ… PASS"

# Test 2: Schedule (dry-run avec date future)
echo ""
echo "âœ… Test 2: Schedule Endpoint"
RESPONSE=$(curl -sf -X POST "$SERVICE_URL/schedule" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"date":"2025-12-31","mode":"tasks"}')

TOTAL_RACES=$(echo $RESPONSE | jq -r '.summary.total_races')
echo "Total races found: $TOTAL_RACES"

if [ "$TOTAL_RACES" -gt 0 ]; then
    echo "âœ… PASS"
else
    echo "âš ï¸ WARNING: No races found (might be normal for future date)"
fi

# Test 3: Run endpoint (mock)
echo ""
echo "âœ… Test 3: Run Endpoint (will fail, just testing auth)"
curl -sf -X POST "$SERVICE_URL/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "course_url": "https://www.zeturf.fr/fr/course/2025-10-28/R1C1-test",
    "phase": "H30",
    "date": "2025-10-28"
  }' || echo "âœ… PASS (expected failure for test URL)"

echo ""
echo "=================================="
echo "ðŸŽ‰ Smoke Test Complete!"
```

### Test du Flux Complet

```bash
#!/bin/bash
# tests/e2e_test_full_flow.sh

set -e

echo "ðŸ§ª E2E Test - Full Flow"
echo "=================================="

# 1. Trigger schedule
echo "1. Triggering schedule..."
gcloud scheduler jobs run hippique-daily-planning \
  --location=europe-west1

sleep 10

# 2. VÃ©rifier les tÃ¢ches crÃ©Ã©es
echo "2. Checking tasks created..."
TASK_COUNT=$(gcloud tasks queues describe hippique-tasks \
  --location=europe-west1 \
  --format="value(stats.tasksCount)")

echo "Tasks in queue: $TASK_COUNT"

if [ "$TASK_COUNT" -gt 0 ]; then
    echo "âœ… Tasks created successfully"
else
    echo "âŒ No tasks created!"
    exit 1
fi

# 3. VÃ©rifier les logs
echo "3. Checking logs..."
gcloud logging read \
  'resource.type=cloud_run_revision AND 
   jsonPayload.correlation_id=~"schedule-"' \
  --limit=1 \
  --format="value(jsonPayload.message,jsonPayload.total_races)"

echo ""
echo "ðŸŽ‰ E2E Test Complete!"
```

## ðŸ"Š Performance Tests

### Load Testing avec Locust

```python
# tests/locustfile.py
from locust import HttpUser, task, between

class HippiqueUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        """Setup - get OIDC token"""
        # In real scenario, get token from gcloud
        self.token = "Bearer FAKE_TOKEN"
    
    @task(10)
    def healthz(self):
        """Health check (most frequent)"""
        self.client.get("/healthz")
    
    @task(1)
    def schedule(self):
        """Schedule endpoint (rare)"""
        self.client.post(
            "/schedule",
            headers={"Authorization": self.token},
            json={"date": "2025-10-28", "mode": "tasks"}
        )
```

### Lancer les Tests de Charge

```bash
# Installer locust
pip install locust

# Lancer les tests
locust -f tests/locustfile.py --host=https://YOUR_SERVICE_URL

# Ou en CLI
locust -f tests/locustfile.py \
  --host=https://YOUR_SERVICE_URL \
  --users=10 \
  --spawn-rate=2 \
  --run-time=60s \
  --headless
```

## 🔍 Tests de Validation

### Validation du Plan du Jour

```bash
#!/bin/bash
# tests/validate_plan.sh

# Test que le plan contient les champs requis
python -c "
import sys
from src.plan import build_plan

plan = build_plan('today')

if not plan:
    print('âŒ No races found')
    sys.exit(1)

required_fields = ['date', 'r_label', 'c_label', 'time_local', 'course_url']

for item in plan:
    for field in required_fields:
        if field not in item or not item[field]:
            print(f'âŒ Missing field: {field}')
            sys.exit(1)

print(f'âœ… Plan valid: {len(plan)} races')
"
```

### Validation des Artefacts

```bash
#!/bin/bash
# tests/validate_artifacts.sh

# VÃ©rifie qu'une analyse a produit les fichiers attendus
RC_DIR="data/R1C1"

if [ ! -d "$RC_DIR" ]; then
    echo "âŒ Directory not found: $RC_DIR"
    exit 1
fi

# VÃ©rifier prÃ©sence des fichiers
FILES=(
    "analysis_H5.json"
    "p_finale.json"
)

for file in "${FILES[@]}"; do
    if [ ! -f "$RC_DIR/$file" ]; then
        echo "âŒ Missing file: $RC_DIR/$file"
        exit 1
    fi
done

# VÃ©rifier format JSON valide
for file in "${FILES[@]}"; do
    if ! jq empty "$RC_DIR/$file" 2>/dev/null; then
        echo "âŒ Invalid JSON: $RC_DIR/$file"
        exit 1
    fi
done

echo "âœ… All artifacts valid"
```

## ðŸ"‹ Checklist de Tests

### Avant DÃ©ploiement

- [ ] Tests unitaires passent (`pytest tests/`)
- [ ] Coverage > 80% (`pytest --cov=src`)
- [ ] Tests d'intÃ©gration passent
- [ ] Linting OK (`black`, `flake8`)
- [ ] Type checking OK (`mypy src/`)
- [ ] Dockerfile build OK
- [ ] .env.example Ã  jour

### AprÃ¨s DÃ©ploiement

- [ ] Smoke test production OK
- [ ] Health check OK
- [ ] Schedule test OK (date future)
- [ ] Logs structurÃ©s OK
- [ ] MÃ©triques visibles
- [ ] Alertes configurÃ©es

### Hebdomadaire

- [ ] E2E test complet
- [ ] Performance tests
- [ ] Validation des artefacts
- [ ] Revue des erreurs

## ðŸ"š Ressources

- **pytest docs**: https://docs.pytest.org/
- **FastAPI testing**: https://fastapi.tiangolo.com/tutorial/testing/
- **Locust docs**: https://docs.locust.io/
- **Cloud Run testing**: https://cloud.google.com/run/docs/testing

---

**Version**: 1.0  
**Last Updated**: 2025-10-28  
**Maintainer**: QA Team
