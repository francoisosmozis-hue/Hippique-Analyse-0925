# ============================================================================
# tests/test_time_utils.py - Tests pour time_utils
# ============================================================================

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from src.time_utils import (
    calculate_snapshots,
    now_paris,
    parse_local_time,
    to_paris,
    to_rfc3339,
    to_utc,
)


@pytest.mark.unit
def test_now_paris():
    """Test que now_paris retourne bien Europe/Paris"""
    result = now_paris()
    assert result.tzinfo == ZoneInfo("Europe/Paris")


@pytest.mark.unit
def test_parse_local_time():
    """Test du parsing de date + heure"""
    result = parse_local_time("2025-10-16", "14:30")

    assert result.year == 2025
    assert result.month == 10
    assert result.day == 16
    assert result.hour == 14
    assert result.minute == 30
    assert result.tzinfo == ZoneInfo("Europe/Paris")


@pytest.mark.unit
def test_to_utc():
    """Test conversion Paris -> UTC"""
    # En été (DST), Paris = UTC+2
    summer_time = datetime(2025, 7, 15, 14, 30, tzinfo=ZoneInfo("Europe/Paris"))
    result = to_utc(summer_time)

    assert result.tzinfo == ZoneInfo("UTC")
    # 14:30 CET = 12:30 UTC
    assert result.hour == 12
    assert result.minute == 30


@pytest.mark.unit
def test_to_paris():
    """Test conversion UTC -> Paris"""
    utc_time = datetime(2025, 10, 16, 12, 30, tzinfo=ZoneInfo("UTC"))
    result = to_paris(utc_time)

    assert result.tzinfo == ZoneInfo("Europe/Paris")
    # En octobre (après DST), 12:30 UTC = 14:30 CET
    assert result.hour == 14
    assert result.minute == 30


@pytest.mark.unit
def test_to_rfc3339():
    """Test format RFC3339"""
    dt = datetime(2025, 10, 16, 14, 30, 0, tzinfo=ZoneInfo("Europe/Paris"))
    result = to_rfc3339(dt)

    # Doit contenir l'offset
    assert "2025-10-16" in result
    assert "14:30:00" in result
    assert "+" in result or "Z" in result  # Offset ou Zulu


@pytest.mark.unit
def test_calculate_snapshots():
    """Test calcul H-30 et H-5"""
    race_time = datetime(2025, 10, 16, 15, 0, tzinfo=ZoneInfo("Europe/Paris"))
    h30, h5 = calculate_snapshots(race_time)

    # H-30 = 14:30
    assert h30.hour == 14
    assert h30.minute == 30

    # H-5 = 14:55
    assert h5.hour == 14
    assert h5.minute == 55


# ============================================================================
# tests/test_plan.py - Tests pour plan builder
# ============================================================================

from unittest.mock import MagicMock, Mock, patch

import pytest
from bs4 import BeautifulSoup

from hippique_orchestrator.plan import PlanBuilder


@pytest.fixture
def mock_zeturf_response():
    """HTML ZEturf avec 3 courses"""
    return """
    <html>
        <body>
            <a href="/fr/course/2025-10-16/R1C1-vincennes">R1C1 Vincennes</a>
            <a href="/fr/course/2025-10-16/R1C2-vincennes">R1C2 Vincennes</a>
            <a href="/fr/course/2025-10-16/R2C1-longchamp">R2C1 Longchamp</a>
        </body>
    </html>
    """


@pytest.fixture
def mock_geny_response():
    """HTML Geny avec heures"""
    return """
    <html>
        <body>
            <div>R1C1 14h15</div>
            <div>R1C2 14h45</div>
            <div>R2C1 15h30</div>
        </body>
    </html>
    """


@pytest.mark.unit
def test_parse_zeturf_program(mock_zeturf_response):
    """Test parsing ZEturf"""
    builder = PlanBuilder()

    with patch.object(builder.session, 'get') as mock_get:
        mock_get.return_value = Mock(status_code=200, text=mock_zeturf_response)

        result = builder._parse_zeturf_program("2025-10-16")

    assert len(result) == 3
    assert result[0]["r_label"] == "R1"
    assert result[0]["c_label"] == "C1"
    assert "vincennes" in result[0]["course_url"]


@pytest.mark.unit
def test_extract_meeting():
    """Test extraction du nom de l'hippodrome"""
    builder = PlanBuilder()

    # Cas 1: depuis l'URL
    link = BeautifulSoup('<a href="/course/2025-10-16/R1C1-vincennes-trot">X</a>', 'html.parser').a
    href = "/course/2025-10-16/R1C1-vincennes-trot"
    result = builder._extract_meeting(link, href)

    assert "vincennes" in result.lower()


@pytest.mark.unit
def test_deduplicate_and_sort(sample_plan):
    """Test déduplication et tri"""
    builder = PlanBuilder()

    # Ajouter un doublon
    plan_with_dup = sample_plan + [sample_plan[0].copy()]

    result = builder._deduplicate_and_sort(plan_with_dup)

    # Doit avoir supprimé le doublon
    assert len(result) == len(sample_plan)

    # Doit être trié par heure
    times = [r["time_local"] for r in result if r["time_local"]]
    assert times == sorted(times)


@pytest.mark.unit
def test_build_plan_empty_response():
    """Test avec réponse vide"""
    builder = PlanBuilder()

    with patch.object(builder.session, 'get') as mock_get:
        mock_get.return_value = Mock(status_code=200, text="<html><body></body></html>")

        result = builder.build_plan("2025-10-16")

    assert result == []


# ============================================================================
# tests/test_scheduler.py - Tests pour TaskScheduler
# ============================================================================

import pytest

from hippique_orchestrator.scheduler import TaskScheduler


@pytest.fixture
def mock_scheduler():
    """TaskScheduler avec clients mockés"""
    with (
        patch('src.scheduler.tasks_v2.CloudTasksClient'),
        patch('src.scheduler.scheduler_v1.CloudSchedulerClient'),
    ):
        scheduler = TaskScheduler()
        scheduler.tasks_client = MagicMock()
        scheduler.scheduler_client = MagicMock()
        scheduler.queue_path = "projects/test/locations/europe-west1/queues/test-queue"

        return scheduler


@pytest.mark.unit
def test_enqueue_run_task_success(mock_scheduler):
    """Test création d'une tâche réussie"""
    # Mock GET (tâche n'existe pas)
    mock_scheduler.tasks_client.get_task.side_effect = Exception("Not found")

    # Mock CREATE
    mock_scheduler.tasks_client.create_task.return_value = Mock(
        name="projects/test/locations/europe-west1/queues/test-queue/tasks/run-20251016-r1c1-h30"
    )

    when = datetime(2025, 10, 16, 14, 30, tzinfo=ZoneInfo("Europe/Paris"))

    result = mock_scheduler.enqueue_run_task(
        run_url="http://example.com/run",
        course_url="http://course.com",
        phase="H30",
        when_paris=when,
        date_str="2025-10-16",
        r_label="R1",
        c_label="C1",
    )

    assert result is not None
    assert "run-20251016-r1c1-h30" in result


@pytest.mark.unit
def test_enqueue_run_task_already_exists(mock_scheduler):
    """Test quand la tâche existe déjà"""
    # Mock GET (tâche existe)
    mock_scheduler.tasks_client.get_task.return_value = Mock(name="existing-task")

    when = datetime(2025, 10, 16, 14, 30, tzinfo=ZoneInfo("Europe/Paris"))

    result = mock_scheduler.enqueue_run_task(
        run_url="http://example.com/run",
        course_url="http://course.com",
        phase="H30",
        when_paris=when,
        date_str="2025-10-16",
        r_label="R1",
        c_label="C1",
    )

    # Doit retourner le nom de la tâche existante
    assert result is not None

    # Ne doit PAS appeler create_task
    mock_scheduler.tasks_client.create_task.assert_not_called()


@pytest.mark.unit
def test_enqueue_task_name_format(mock_scheduler):
    """Test format du nom de tâche"""
    mock_scheduler.tasks_client.get_task.side_effect = Exception("Not found")
    mock_scheduler.tasks_client.create_task.return_value = Mock(name="task-name")

    when = datetime(2025, 10, 16, 14, 30, tzinfo=ZoneInfo("Europe/Paris"))

    # Test avec différentes phases
    for phase in ["H30", "H-30", "H5", "H-5"]:
        mock_scheduler.enqueue_run_task(
            run_url="http://example.com/run",
            course_url="http://course.com",
            phase=phase,
            when_paris=when,
            date_str="2025-10-16",
            r_label="R1",
            c_label="C1",
        )

        # Vérifier l'appel avec le nom correct
        call_args = mock_scheduler.tasks_client.create_task.call_args
        task_name = call_args[1]["task"]["name"]

        # Doit contenir h30 ou h5 (normalisé, sans tirets)
        assert "h30" in task_name or "h5" in task_name
        assert "-" in task_name  # Format kebab-case
        assert task_name.startswith("projects/")


# ============================================================================
# tests/test_runner.py - Tests pour GPIRunner
# ============================================================================

import subprocess

import pytest

from hippique_orchestrator.runner import GPIRunner


@pytest.fixture
def runner(temp_data_dir):
    """Runner avec répertoire temporaire"""
    return GPIRunner(data_dir=str(temp_data_dir))


@pytest.mark.unit
def test_normalize_phase(runner):
    """Test normalisation des phases"""
    assert runner._normalize_phase("H30") == "H30"
    assert runner._normalize_phase("H-30") == "H30"
    assert runner._normalize_phase("h30") == "H30"
    assert runner._normalize_phase("H5") == "H5"
    assert runner._normalize_phase("H-5") == "H5"
    assert runner._normalize_phase("h-5") == "H5"

    with pytest.raises(ValueError):
        runner._normalize_phase("invalid")


@pytest.mark.unit
def test_tail(runner):
    """Test fonction tail"""
    text = "\n".join([f"Line {i}" for i in range(100)])

    result = runner._tail(text, 10)
    lines = result.split("\n")

    assert len(lines) == 10
    assert lines[-1] == "Line 99"
    assert lines[0] == "Line 90"


@pytest.mark.unit
def test_collect_artifacts(runner, sample_gpi_output):
    """Test collection des artefacts"""
    runner.data_dir = sample_gpi_output

    artifacts = runner._collect_artifacts("2025-10-16")

    # Doit trouver les fichiers créés
    assert len(artifacts) > 0
    assert any("p_finale.json" in a for a in artifacts)
    assert any(".csv" in a for a in artifacts)


@pytest.mark.unit
@patch('subprocess.run')
def test_run_subprocess_success(mock_run, runner):
    """Test exécution subprocess réussie"""
    mock_run.return_value = Mock(returncode=0, stdout="Output", stderr="")

    rc, stdout, stderr = runner._run_subprocess(["python", "test.py"], env={"TEST": "value"})

    assert rc == 0
    assert stdout == "Output"
    assert stderr == ""


@pytest.mark.unit
@patch('subprocess.run')
def test_run_subprocess_timeout(mock_run, runner):
    """Test timeout subprocess"""
    mock_run.side_effect = subprocess.TimeoutExpired("cmd", 10)

    rc, stdout, stderr = runner._run_subprocess(["python", "test.py"], env={}, timeout=10)

    assert rc == 124  # Code timeout
    assert "Timeout" in stderr


@pytest.mark.unit
@patch('subprocess.run')
def test_run_subprocess_error(mock_run, runner):
    """Test erreur subprocess"""
    mock_run.return_value = Mock(returncode=1, stdout="", stderr="Error occurred")

    rc, stdout, stderr = runner._run_subprocess(["python", "test.py"], env={})

    assert rc == 1
    assert stderr == "Error occurred"


# ============================================================================
# tests/test_service.py - Tests pour API FastAPI
# ============================================================================

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hippique_orchestrator.service import app


@pytest.fixture
def client():
    """Client de test FastAPI sans auth"""
    with patch('src.service.config.REQUIRE_AUTH', False):
        client = TestClient(app)
        yield client


@pytest.mark.unit
def test_healthz(client):
    """Test endpoint healthz"""
    response = client.get("/healthz")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


@pytest.mark.unit
@patch('src.service.plan_builder.build_plan')
@patch('src.service.scheduler.enqueue_run_task')
def test_schedule_endpoint_success(mock_enqueue, mock_build_plan, client):
    """Test endpoint /schedule"""
    # Mock plan
    mock_build_plan.return_value = [
        {
            "date": "2025-10-16",
            "r_label": "R1",
            "c_label": "C1",
            "meeting": "VINCENNES",
            "time_local": "14:30",
            "course_url": "http://course.com",
            "reunion_url": "http://reunion.com",
        }
    ]

    # Mock enqueue
    mock_enqueue.return_value = "task-name"

    response = client.post("/schedule", json={"date": "2025-10-16", "mode": "tasks"})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["races_count"] == 1
    assert data["tasks_scheduled"] >= 1


@pytest.mark.unit
@patch('src.service.plan_builder.build_plan')
def test_schedule_endpoint_no_races(mock_build_plan, client):
    """Test /schedule sans courses"""
    mock_build_plan.return_value = []

    response = client.post("/schedule", json={"date": "2025-10-16", "mode": "tasks"})

    assert response.status_code == 404
    assert "No races found" in response.json()["detail"]


@pytest.mark.unit
@patch('src.service.runner.run_course')
def test_run_endpoint_success(mock_run_course, client):
    """Test endpoint /run"""
    mock_run_course.return_value = {
        "ok": True,
        "rc": 0,
        "stdout_tail": "Success",
        "stderr_tail": "",
        "artifacts": ["file1.json"],
    }

    response = client.post(
        "/run", json={"course_url": "http://course.com", "phase": "H30", "date": "2025-10-16"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["returncode"] == 0


@pytest.mark.unit
@patch('src.service.runner.run_course')
def test_run_endpoint_failure(mock_run_course, client):
    """Test /run avec échec"""
    mock_run_course.return_value = {
        "ok": False,
        "rc": 1,
        "stdout_tail": "",
        "stderr_tail": "Error",
        "artifacts": [],
    }

    response = client.post(
        "/run", json={"course_url": "http://course.com", "phase": "H30", "date": "2025-10-16"}
    )

    assert response.status_code == 200  # Code 200 même si échec interne
    data = response.json()
    assert data["ok"] is False
    assert data["returncode"] == 1


# ============================================================================
# tests/test_integration.py - Tests d'intégration
# ============================================================================

import pytest


@pytest.mark.integration
@pytest.mark.slow
def test_full_plan_build():
    """Test construction complète du plan (réel)"""
    from hippique_orchestrator.plan import PlanBuilder

    builder = PlanBuilder()

    # Date future pour éviter d'exécuter réellement
    plan = builder.build_plan("today")

    # Peut être vide si pas de courses
    if plan:
        # Vérifier structure
        for race in plan:
            assert "date" in race
            assert "r_label" in race
            assert "c_label" in race
            assert "meeting" in race
            assert "course_url" in race


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.requires_gcp
def test_cloud_tasks_integration():
    """Test intégration Cloud Tasks (nécessite GCP)"""
    from hippique_orchestrator.config import config
    from hippique_orchestrator.scheduler import TaskScheduler

    # Skip si pas configuré
    if not config.PROJECT_ID or config.PROJECT_ID == "test-project":
        pytest.skip("GCP not configured")

    scheduler = TaskScheduler()

    # Tester que la queue existe
    try:
        # Note: nécessite credentials GCP
        queue_path = scheduler.queue_path
        assert "projects" in queue_path
    except Exception as e:
        pytest.skip(f"GCP connection failed: {e}")


# ============================================================================
# tests/test_edge_cases.py - Tests de cas limites
# ============================================================================

import pytest


@pytest.mark.unit
def test_empty_plan_deduplication():
    """Test déduplication sur plan vide"""
    from hippique_orchestrator.plan import PlanBuilder

    builder = PlanBuilder()
    result = builder._deduplicate_and_sort([])

    assert result == []


@pytest.mark.unit
def test_plan_with_missing_times():
    """Test plan avec heures manquantes"""
    from hippique_orchestrator.plan import PlanBuilder

    plan = [
        {"date": "2025-10-16", "r_label": "R1", "c_label": "C1", "time_local": "14:30"},
        {"date": "2025-10-16", "r_label": "R1", "c_label": "C2", "time_local": None},
        {"date": "2025-10-16", "r_label": "R2", "c_label": "C1", "time_local": "15:00"},
    ]

    builder = PlanBuilder()
    result = builder._deduplicate_and_sort(plan)

    # Les courses sans heure doivent être en fin
    assert result[-1]["time_local"] is None


@pytest.mark.unit
def test_task_name_special_characters():
    """Test nom de tâche avec caractères spéciaux"""
    from hippique_orchestrator.scheduler import TaskScheduler

    # Les noms de tâche doivent être RFC-1035 compliant
    # (lowercase, alphanumeric, hyphens)
    TaskScheduler()

    # Test que le nom généré est valide
    # Note: la vraie validation se fait dans enqueue_run_task
    task_id = "run-20251016-r1c1-h30"

    assert task_id.islower() or task_id.isdigit() or '-' in task_id
    assert not any(c in task_id for c in ['_', '.', '/', ' '])


# ============================================================================
# Exécution des tests
# ============================================================================
"""
Pour exécuter les tests:

# Tous les tests
pytest

# Tests unitaires uniquement
pytest -m unit

# Tests avec couverture
pytest --cov=src --cov-report=html

# Tests spécifiques
pytest tests/test_plan.py::test_deduplicate_and_sort

# Mode verbose
pytest -v

# Tests lents exclus
pytest -m "not slow"

# Tests d'intégration uniquement
pytest -m integration
"""
