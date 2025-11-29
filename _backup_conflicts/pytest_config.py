# ============================================================================
# pytest.ini - Configuration pytest
# ============================================================================
"""
[pytest]
testpaths = tests
python_files = test_*.py *_test.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --tb=short
    --strict-markers
    --disable-warnings
    --color=yes
    --cov=src
    --cov-report=html
    --cov-report=term-missing
markers =
    unit: Unit tests
    integration: Integration tests
    slow: Slow tests
    requires_gcp: Tests requiring GCP resources
"""

# ============================================================================
# tests/conftest.py - Fixtures pytest
# ============================================================================


# Imports depuis le projet
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from hippique_orchestrator.logging_utils import setup_logger

# ----------------------------------------------------------------------------
# Fixtures de configuration
# ----------------------------------------------------------------------------

@pytest.fixture
def test_config():
    """Configuration de test"""
    return Config(
        PROJECT_ID="test-project",
        REGION="europe-west1",
        SERVICE_NAME="test-service",
        SERVICE_URL="http://localhost:8080",
        QUEUE_ID="test-queue",
        REQUIRE_AUTH=False,
        GCS_BUCKET=None,
        LOCAL_DATA_DIR=tempfile.mkdtemp(),
        TIMEZONE="Europe/Paris",
        REQUEST_TIMEOUT=5,
        MAX_RETRIES=1,
        RATE_LIMIT_DELAY=0.1,
        USER_AGENT="TestAgent/1.0",
        GPI_BUDGET_PER_RACE=5.0,
        GPI_MIN_EV_PERCENT=40.0
    )


@pytest.fixture
def test_logger():
    """Logger de test"""
    return setup_logger("test")


# ----------------------------------------------------------------------------
# Fixtures de données
# ----------------------------------------------------------------------------

@pytest.fixture
def sample_plan():
    """Plan de test avec 3 courses"""
    return [
        {
            "date": "2025-10-16",
            "r_label": "R1",
            "c_label": "C1",
            "meeting": "VINCENNES",
            "time_local": "14:15",
            "course_url": "https://www.zeturf.fr/fr/course/2025-10-16/R1C1-vincennes",
            "reunion_url": "https://www.zeturf.fr/fr/reunion/2025-10-16/R1"
        },
        {
            "date": "2025-10-16",
            "r_label": "R1",
            "c_label": "C2",
            "meeting": "VINCENNES",
            "time_local": "14:45",
            "course_url": "https://www.zeturf.fr/fr/course/2025-10-16/R1C2-vincennes",
            "reunion_url": "https://www.zeturf.fr/fr/reunion/2025-10-16/R1"
        },
        {
            "date": "2025-10-16",
            "r_label": "R2",
            "c_label": "C1",
            "meeting": "LONGCHAMP",
            "time_local": "15:30",
            "course_url": "https://www.zeturf.fr/fr/course/2025-10-16/R2C1-longchamp",
            "reunion_url": "https://www.zeturf.fr/fr/reunion/2025-10-16/R2"
        }
    ]


@pytest.fixture
def zeturf_html_sample():
    """HTML ZEturf simplifié pour tests de parsing"""
    return """
    <html>
        <body>
            <div class="program">
                <a href="/fr/course/2025-10-16/R1C1-vincennes-trot">R1C1 Vincennes</a>
                <a href="/fr/course/2025-10-16/R1C2-vincennes-trot">R1C2 Vincennes</a>
                <a href="/fr/course/2025-10-16/R2C1-longchamp-plat">R2C1 Longchamp</a>
            </div>
        </body>
    </html>
    """


@pytest.fixture
def geny_html_sample():
    """HTML Geny simplifié pour tests de parsing"""
    return """
    <html>
        <body>
            <div class="race-card">
                <span class="race-id">R1C1</span>
                <span class="race-time">14h15</span>
                <span class="hippodrome">VINCENNES</span>
            </div>
            <div class="race-card">
                <span class="race-id">R1C2</span>
                <span class="race-time">14h45</span>
                <span class="hippodrome">VINCENNES</span>
            </div>
        </body>
    </html>
    """


# ----------------------------------------------------------------------------
# Mocks GCP
# ----------------------------------------------------------------------------

@pytest.fixture
def mock_tasks_client():
    """Mock du client Cloud Tasks"""
    mock = MagicMock()
    mock.queue_path.return_value = "projects/test/locations/europe-west1/queues/test-queue"
    mock.create_task.return_value = Mock(name="projects/.../tasks/test-task")
    return mock


@pytest.fixture
def mock_scheduler_client():
    """Mock du client Cloud Scheduler"""
    mock = MagicMock()
    mock.create_job.return_value = Mock(name="projects/.../jobs/test-job")
    return mock


@pytest.fixture
def mock_storage_client():
    """Mock du client Cloud Storage"""
    mock = MagicMock()
    bucket = MagicMock()
    blob = MagicMock()
    bucket.blob.return_value = blob
    mock.bucket.return_value = bucket
    return mock


# ----------------------------------------------------------------------------
# Fixtures HTTP
# ----------------------------------------------------------------------------

@pytest.fixture
def mock_requests_session():
    """Mock de requests.Session"""
    with patch('requests.Session') as mock:
        session = mock.return_value
        session.get.return_value = Mock(
            status_code=200,
            text="<html></html>",
            json=lambda: {}
        )
        yield session


# ----------------------------------------------------------------------------
# Fixtures temporelles
# ----------------------------------------------------------------------------

@pytest.fixture
def fixed_datetime():
    """Datetime fixe pour tests prévisibles"""
    fixed_dt = datetime(2025, 10, 16, 9, 0, 0)

    with patch('src.time_utils.now_paris') as mock:
        mock.return_value = fixed_dt
        yield fixed_dt


# ----------------------------------------------------------------------------
# Fixtures filesystem
# ----------------------------------------------------------------------------

@pytest.fixture
def temp_data_dir():
    """Répertoire temporaire pour tests"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_gpi_output(temp_data_dir):
    """Fichiers GPI simulés"""
    files = {
        "p_finale.json": {"combos": [], "budget": 5.0},
        "results.csv": "horse,odds,prediction\nCheval1,3.5,0.85",
        "report.xlsx": b"fake_excel_content"
    }

    for filename, content in files.items():
        filepath = temp_data_dir / filename
        if isinstance(content, bytes):
            filepath.write_bytes(content)
        elif isinstance(content, dict):
            import json
            filepath.write_text(json.dumps(content))
        else:
            filepath.write_text(content)

    return temp_data_dir


# ----------------------------------------------------------------------------
# Fixtures FastAPI
# ----------------------------------------------------------------------------

@pytest.fixture
def test_client():
    """Client de test FastAPI"""
    from fastapi.testclient import TestClient

    from hippique_orchestrator.service import app

    # Désactiver l'authentification pour les tests
    with patch('src.service.config.REQUIRE_AUTH', False):
        client = TestClient(app)
        yield client


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def assert_valid_plan(plan: list):
    """Valide la structure d'un plan"""
    assert isinstance(plan, list)
    for race in plan:
        assert "date" in race
        assert "r_label" in race
        assert "c_label" in race
        assert "meeting" in race
        assert "course_url" in race
        assert race["r_label"].startswith("R")
        assert race["c_label"].startswith("C")


def assert_valid_task_name(task_name: str):
    """Valide un nom de tâche Cloud Tasks"""
    import re
    # Format: run-YYYYMMDD-rXcY-h30|h5
    pattern = r"run-\d{8}-r\d+c\d+-(h30|h5)"
    assert re.match(pattern, task_name), f"Invalid task name: {task_name}"


# ----------------------------------------------------------------------------
# Markers
# ----------------------------------------------------------------------------

def pytest_configure(config):
    """Configuration des markers"""
    config.addinivalue_line(
        "markers", "unit: Unit tests"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests requiring external services"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take > 1 second"
    )
    config.addinivalue_line(
        "markers", "requires_gcp: Tests requiring GCP credentials/resources"
    )


# ============================================================================
# tests/test_plan.py - Exemple de test unitaire
# ============================================================================
"""
import pytest
from hippique_orchestrator.plan import PlanBuilder

@pytest.mark.unit
def test_deduplicate_plan(sample_plan):
    '''Test de déduplication du plan'''
    # Ajouter un doublon
    plan_with_dup = sample_plan + [sample_plan[0]]

    builder = PlanBuilder()
    unique_plan = builder._deduplicate_and_sort(plan_with_dup)

    assert len(unique_plan) == len(sample_plan)
    assert_valid_plan(unique_plan)

@pytest.mark.unit
def test_parse_zeturf_program(mock_requests_session, zeturf_html_sample):
    '''Test du parsing ZEturf'''
    mock_requests_session.get.return_value.text = zeturf_html_sample

    builder = PlanBuilder()
    with patch('src.plan.requests.Session', return_value=mock_requests_session):
        plan = builder._parse_zeturf_program("2025-10-16")

    assert len(plan) >= 3
    assert_valid_plan(plan)

@pytest.mark.slow
@pytest.mark.integration
def test_build_plan_real(test_config):
    '''Test d'intégration avec sources réelles (marqué slow)'''
    builder = PlanBuilder()
    plan = builder.build_plan("today")

    # Peut échouer si pas de courses
    if plan:
        assert_valid_plan(plan)
"""
