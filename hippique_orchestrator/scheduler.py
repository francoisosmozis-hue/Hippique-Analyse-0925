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
from datetime import datetime, timedelta, timezone
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
# Task Name Generation
# ============================================

def _generate_task_name(date: str, r_label: str, c_label: str, phase: str) -> str:
    """
    Génère un nom de tâche déterministe (idempotence).
    Format: run-YYYYMMDD-rXcY-{h30|h5}
    """
    date_compact = date.replace("-", "")
    r_num = r_label[1:].lower()
    c_num = c_label[1:].lower()
    phase_lower = phase.lower().replace("-", "")
    return f"run-{date_compact}-r{r_num}c{c_num}-{phase_lower}"

def _sanitize_task_name(name: str) -> str:
    """Sanitize task name to comply with RFC-1035."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9-]', '-', name)
    name = name.strip('-')
    if name and not name[0].isalpha():
        name = 'task-' + name
    return name[:500]

# ============================================
# Cloud Tasks - Main API
# ============================================

def enqueue_run_task(
    client: tasks_v2.CloudTasksClient,
    course_url: str,
    phase: str,
    date: str,
    race_time_local: str,
    r_label: str,
    c_label: str,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> str | None:
    """Crée une Cloud Task pour exécuter une analyse de course."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}
    logger.debug(f"Entering enqueue_run_task for {r_label}{c_label}-{phase}", extra=log_extra)
    offset = 30 if phase == "H30" else 5

    try:
        race_datetime_local = datetime.strptime(f"{date} {race_time_local}", "%Y-%m-%d %H:%M")
    except ValueError as e:
        logger.error(f"Invalid race time: {race_time_local}", exc_info=e)
        return None

    snapshot_datetime_local = race_datetime_local - timedelta(minutes=offset)
    snapshot_datetime_utc = convert_local_to_utc(snapshot_datetime_local)

    # Cloud Tasks API requires schedule_time to be in the future.
    # Add a buffer of a few seconds to be safe.
    if snapshot_datetime_utc < datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(seconds=5):
        logger.warning(
            f"Skipping task for {r_label}{c_label} phase {phase} because its schedule time is in the past.",
            extra={**log_extra, "race_time_local": race_time_local, "snapshot_time_utc": format_rfc3339(snapshot_datetime_utc)},
        )
        return None

    task_name_short = _generate_task_name(date, r_label, c_label, phase)
    task_name_safe = _sanitize_task_name(task_name_short)

    parent = f"projects/{config.PROJECT_ID}/locations/{config.REGION}/queues/{config.QUEUE_ID}"
    task_path = f"{parent}/tasks/{task_name_safe}"

    try:
        client.get_task(name=task_path)
        logger.info(
            f"Task {task_name_safe} already exists, skipping",
            extra={**log_extra, "task_name": task_name_safe},
        )
        return task_path
    except gcp_exceptions.NotFound:
        pass
    except Exception as e:
        logger.warning(f"Error checking task existence: {str(e)}", exc_info=True, extra=log_extra)

    payload = {
        "course_url": course_url,
        "phase": phase,
        "date": date,
        "trace_id": trace_id,
    }

    task = {
        "name": task_path,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{config.cloud_run_url}/tasks/run-phase",
            "headers": {
                "Content-Type": "application/json",
                "X-Correlation-ID": correlation_id or "",
            },
            "body": json.dumps(payload).encode(),
        },
        "schedule_time": timestamp_pb2.Timestamp(seconds=int(snapshot_datetime_utc.timestamp())),
    }

    if config.REQUIRE_AUTH:
        task["http_request"]["oidc_token"] = {
            "service_account_email": config.SERVICE_ACCOUNT_EMAIL,
            "audience": config.OIDC_AUDIENCE,
        }

    try:
        response = client.create_task(parent=parent, task=task)
        logger.info(
            f"Task created: {response.name}",
            extra={
                **log_extra,
                "task_name": task_name_safe,
                "phase": phase,
                "race": f"{r_label}{c_label}",
                "race_time": race_time_local,
                "snapshot_time_utc": format_rfc3339(snapshot_datetime_utc),
                "snapshot_time_local": snapshot_datetime_local.strftime("%Y-%m-%d %H:%M"),
            },
        )
        return response.name
    except gcp_exceptions.AlreadyExists:
        logger.info(
            f"Task {task_name_safe} already exists (race condition), skipping",
            extra=log_extra,
        )
        return task_path
    except Exception as e:
        logger.error(
            f"Failed to create task {task_name_safe}: {e}",
            exc_info=True,
            extra=log_extra,
        )
        return None

# ============================================
# Scheduler All Races
# ============================================

def schedule_all_races(
    plan: list[dict], mode: str, correlation_id: str, trace_id: str
) -> list[dict[str, Any]]:
    """
    Orchestre la planification de toutes les courses d'un plan donné.
    """
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}
    logger.debug(f"Starting schedule_all_races with {len(plan)} races", extra=log_extra)

    try:
        client = tasks_v2.CloudTasksClient()
        logger.info("Cloud Tasks client initialized successfully.")
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize Cloud Tasks client: {e}", exc_info=True, extra=log_extra)
        # Cannot proceed without a client. Return failure for all potential tasks.
        return [{"phase": "H30", "ok": False, "error": "Client initialization failed"},
                {"phase": "H5", "ok": False, "error": "Client initialization failed"}] * len(plan)

    results = []
    for i, race_plan in enumerate(plan):
        try:
            r_label = race_plan["r_label"]
            c_label = race_plan["c_label"]
            course_url = race_plan["course_url"]
            date_str = race_plan["date"]
            race_time_local = race_plan["time_local"]
        except KeyError as e:
            logger.error(f"Missing key in race_plan item {i}: {e}", exc_info=True, extra=log_extra)
            continue

        logger.debug(f"Attempting to enqueue tasks for {r_label}{c_label}", extra=log_extra)

        try:
            # H30 task
            h30_task_ok = enqueue_run_task(
                client=client,
                course_url=course_url,
                phase="H30",
                date=date_str,
                race_time_local=race_time_local,
                r_label=r_label,
                c_label=c_label,
                correlation_id=correlation_id,
                trace_id=trace_id,
            ) is not None
            results.append({"phase": "H30", "ok": h30_task_ok})

            # H5 task
            h5_task_ok = enqueue_run_task(
                client=client,
                course_url=course_url,
                phase="H5",
                date=date_str,
                race_time_local=race_time_local,
                r_label=r_label,
                c_label=c_label,
                correlation_id=correlation_id,
                trace_id=trace_id,
            ) is not None
            results.append({"phase": "H5", "ok": h5_task_ok})
        except Exception as e:
            logger.error(f"Unhandled exception during enqueue_run_task call for {r_label}{c_label}: {e}", exc_info=True, extra=log_extra)
            results.append({"phase": "H30", "ok": False, "error": str(e)})
            results.append({"phase": "H5", "ok": False, "error": str(e)})

    logger.debug("Finished schedule_all_races", extra=log_extra)
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
    """Crée un job Cloud Scheduler one-shot (fallback)."""
    logger.warning("Cloud Scheduler fallback not implemented, use Cloud Tasks instead")
    return False
