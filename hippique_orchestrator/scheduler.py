"""
src/scheduler.py - Programmation Cloud Tasks/Scheduler

Programme les analyses H-30 et H-5 pour chaque course du jour.

Mode principal: Cloud Tasks (recommandé)
Mode fallback: Cloud Scheduler one-shot jobs

Idempotence: Noms de tâches déterministes pour éviter doublons
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from google.api_core import exceptions as gcp_exceptions
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.time_utils import convert_local_to_utc, format_rfc3339

config = get_config()



logger = get_logger(__name__)

# ============================================
# Cloud Tasks Client (singleton)
# ============================================

_tasks_client: tasks_v2.CloudTasksClient | None = None

def get_tasks_client() -> tasks_v2.CloudTasksClient:
    """Get or create Cloud Tasks client (singleton)"""
    global _tasks_client
    if _tasks_client is None:
        _tasks_client = tasks_v2.CloudTasksClient()
    return _tasks_client

# ============================================
# Task Name Generation
# ============================================

def _generate_task_name(date: str, r_label: str, c_label: str, phase: str) -> str:
    """
    Génère un nom de tâche déterministe (idempotence).

    Format: run-YYYYMMDD-rXcY-{h30|h5}

    Args:
        date: YYYY-MM-DD
        r_label: "R1"
        c_label: "C3"
        phase: "H30" ou "H5"

    Returns:
        "run-20251016-r1c3-h30"
    """
    date_compact = date.replace("-", "")
    r_num = r_label[1:].lower()
    c_num = c_label[1:].lower()
    phase_lower = phase.lower().replace("-", "")

    return f"run-{date_compact}-r{r_num}c{c_num}-{phase_lower}"

def _sanitize_task_name(name: str) -> str:
    """
    Sanitize task name to comply with RFC-1035.

    Rules:
    - Must be 1-500 characters
    - Must contain only lowercase letters, numbers, hyphens
    - Must start with a letter
    - Must end with a letter or number
    """
    # Convert to lowercase
    name = name.lower()

    # Replace invalid characters with hyphens
    name = re.sub(r'[^a-z0-9-]', '-', name)

    # Remove leading/trailing hyphens
    name = name.strip('-')

    # Ensure starts with letter
    if name and not name[0].isalpha():
        name = 'task-' + name

    # Truncate to 500 chars
    name = name[:500]

    return name

# ============================================
# Cloud Tasks - Main API
# ============================================

def enqueue_run_task(
    course_url: str,
    phase: str,
    date: str,
    race_time_local: str,
    r_label: str,
    c_label: str,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> str | None:
    """
    Crée une Cloud Task pour exécuter une analyse de course.

    Args:
        course_url: URL ZEturf de la course
        phase: "H30" ou "H5"
        date: YYYY-MM-DD
        race_time_local: "HH:MM" (Europe/Paris)
        r_label: "R1"
        c_label: "C3"
        correlation_id: ID de corrélation pour logs
        trace_id: ID de traçabilité pour le suivi de bout en bout

    Returns:
        Nom de la tâche créée ou None si échec
    """
    # Calculate snapshot time (H-30 or H-5 before race)
    offset = 30 if phase == "H30" else 5

    # Parse race time (Europe/Paris)
    try:
        race_datetime_local = datetime.strptime(f"{date} {race_time_local}", "%Y-%m-%d %H:%M")
    except ValueError as e:
        logger.error(f"Invalid race time: {race_time_local}", exc_info=e)
        return None

    # Calculate snapshot time (still in Europe/Paris)
    snapshot_datetime_local = race_datetime_local - timedelta(minutes=offset)

    # Convert to UTC
    snapshot_datetime_utc = convert_local_to_utc(snapshot_datetime_local)

    # Generate task name (deterministic for idempotence)
    task_name_short = _generate_task_name(date, r_label, c_label, phase)
    task_name_safe = _sanitize_task_name(task_name_short)

    # Full task path
    logger.info(f"Cloud Tasks parent path components: project_id={config.project_id}, region={config.region}, queue_id={config.queue_id}")
    parent = f"projects/{config.project_id}/locations/{config.region}/queues/{config.queue_id}"
    task_path = f"{parent}/tasks/{task_name_safe}"

    # Check if task already exists (idempotence)
    client = get_tasks_client()
    try:
        client.get_task(name=task_path)
        logger.info(
            f"Task {task_name_safe} already exists, skipping",
            correlation_id=correlation_id,
            trace_id=trace_id,
            task_name=task_name_safe,
        )
        return task_path
    except gcp_exceptions.NotFound:
        # Task doesn't exist, proceed with creation
        pass
    except Exception as e:
        logger.warning(f"Error checking task existence: {str(e)}", exc_info=e)
        # Continue anyway

    # Build HTTP request payload
    payload = {
        "course_url": course_url,
        "phase": phase,
        "date": date,
        "trace_id": trace_id,
    }

    # Build Cloud Task
    task = {
        "name": task_path,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{config.cloud_run_url}/run",
            "headers": {
                "Content-Type": "application/json",
                "X-Correlation-ID": correlation_id or "",
            },
            "body": json.dumps(payload).encode(),
        },
        "schedule_time": timestamp_pb2.Timestamp(
            seconds=int(snapshot_datetime_utc.timestamp())
        ),
    }

    # Add OIDC token if auth required
    if config.require_auth:
        task["http_request"]["oidc_token"] = {
            "service_account_email": config.service_account_email,
            "audience": config.oidc_audience,
        }

    # Create task
    try:
        response = client.create_task(parent=parent, task=task)

        logger.info(
            f"Task created: {task_name_safe}",
            correlation_id=correlation_id,
            trace_id=trace_id,
            task_name=task_name_safe,
            phase=phase,
            race=f"{r_label}{c_label}",
            race_time=race_time_local,
            snapshot_time_utc=format_rfc3339(snapshot_datetime_utc),
            snapshot_time_local=snapshot_datetime_local.strftime("%Y-%m-%d %H:%M"),
        )

        return response.name

    except gcp_exceptions.AlreadyExists:
        # Race condition: task was created between our check and create
        logger.info(
            f"Task {task_name_safe} already exists (race condition), skipping",
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        return task_path

    except Exception as e:
        logger.error(
            f"Failed to create task {task_name_safe}: {e}",
            correlation_id=correlation_id,
            trace_id=trace_id,
            exc_info=e,
        )
        return None

# ============================================
# Scheduler All Races
# ============================================

def schedule_all_races(
    plan: list[dict[str, Any]],
    mode: str = "tasks",
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Programme toutes les courses du plan (H-30 + H-5).

    Args:
        plan: Liste de courses avec time_local
        mode: "tasks" (Cloud Tasks) ou "scheduler" (Cloud Scheduler fallback)
        correlation_id: ID de corrélation pour logs
        trace_id: ID de traçabilité pour le suivi de bout en bout

    Returns:
        Liste de résultats par tâche:
        [
            {
                "race": "R1C3",
                "phase": "H30",
                "ok": true,
                "task_name": "run-20251016-r1c3-h30",
                "snapshot_time_utc": "2025-10-16T12:30:00Z",
                "snapshot_time_local": "2025-10-16 14:30"
            },
            ...
        ]
    """
    if mode != "tasks":
        logger.warning(f"Mode '{mode}' not supported yet, using 'tasks'")
        mode = "tasks"

    results = []

    for race in plan:
        r_label = race["r_label"]
        c_label = race["c_label"]
        course_url = race["course_url"]
        time_local = race["time_local"]
        date = race["date"]

        # Schedule H-30
        task_h30 = enqueue_run_task(
            course_url=course_url,
            phase="H30",
            date=date,
            race_time_local=time_local,
            r_label=r_label,
            c_label=c_label,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        results.append({
            "race": f"{r_label}{c_label}",
            "phase": "H30",
            "ok": task_h30 is not None,
            "task_name": task_h30 or "",
            "race_time_local": time_local,
        })

        # Schedule H-5
        task_h5 = enqueue_run_task(
            course_url=course_url,
            phase="H5",
            date=date,
            race_time_local=time_local,
            r_label=r_label,
            c_label=c_label,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        results.append({
            "race": f"{r_label}{c_label}",
            "phase": "H5",
            "ok": task_h5 is not None,
            "task_name": task_h5 or "",
            "race_time_local": time_local,
        })

    # Summary
    total = len(results)
    success = sum(1 for r in results if r["ok"])
    failed = total - success

    logger.info(
        f"Scheduling complete: {success}/{total} tasks created ({failed} failed)",
        correlation_id=correlation_id,
        trace_id=trace_id,
        total=total,
        success=success,
        failed=failed,
    )

    return results

# ============================================
# Cloud Scheduler Fallback (optional)
# ============================================

def create_one_shot_scheduler_job(
    job_name: str,
    schedule_time_utc: datetime,
    payload: dict[str, Any],
    correlation_id: str | None = None,
) -> bool:
    """
    Crée un job Cloud Scheduler one-shot (fallback).

    NOTE: Cloud Scheduler ne supporte pas vraiment les "one-shot" jobs.
    Cette approche nécessite de créer un job avec cron "0 0 1 1 *" (jamais)
    puis de le déclencher manuellement ou le supprimer après exécution.

    Recommandation: Utiliser Cloud Tasks à la place.

    Args:
        job_name: Nom du job (doit être unique)
        schedule_time_utc: DateTime UTC d'exécution
        payload: Body JSON à envoyer au service
        correlation_id: ID de corrélation pour logs

    Returns:
        True si succès, False sinon
    """
    logger.warning("Cloud Scheduler fallback not implemented, use Cloud Tasks instead")
    return False
