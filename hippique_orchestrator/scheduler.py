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
import logging
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
    print(f"DEBUG_PRINT: Entering enqueue_run_task for {r_label}{c_label}-{phase}")
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
    task_name_short = _generate_task_name(date, r_label, c_label, phase)
    task_name_safe = _sanitize_task_name(task_name_short)

    parent = f"projects/{config.PROJECT_ID}/locations/{config.REGION}/queues/{config.QUEUE_ID}"
    task_path = f"{parent}/tasks/{task_name_safe}"

    client = get_tasks_client()
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

    logger.debug(
        f"Constructed Cloud Task for {task_name_safe}: "
        f"URL='{task['http_request']['url']}', "
        f"Auth_Required={config.REQUIRE_AUTH}, "
        f"OIDC_Audience='{config.OIDC_AUDIENCE}'" if config.REQUIRE_AUTH else "No OIDC Auth",
        extra={**log_extra, "task_name": task_name_safe, "task_payload_url": task['http_request']['url'], "auth_required": config.REQUIRE_AUTH}
    )

    logger.debug(
        f"Attempting to create task: {task_name_safe} with details: {task}",
        extra={
            **log_extra,
            "task_payload_url": task["http_request"]["url"],
            "task_payload_body": task["http_request"]["body"].decode(),
            "task_schedule_time": task["schedule_time"].seconds,
        }
    )
    print(f"DEBUG_PRINT: Creating task {task_name_safe} with URL: {task['http_request']['url']} and OIDC_Audience: {task['http_request'].get('oidc_token', {}).get('audience')}")
    try:
        response = client.create_task(parent=parent, task=task)
        logger.info(
            f"Task created: {task_name_safe}. Response name: {response.name}",
            extra={
                **log_extra,
                "task_name": task_name_safe,
                "phase": phase,
                "race": f"{r_label}{c_label}",
                "race_time": race_time_local,
                "snapshot_time_utc": format_rfc3339(snapshot_datetime_utc),
                "snapshot_time_local": snapshot_datetime_local.strftime("%Y-%m-%d %H:%M"),
                "task_creation_response_name": response.name,
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
    print(f"DEBUG_PRINT: Starting schedule_all_races with {len(plan)} races")
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}
    logger.debug(f"Starting schedule_all_races with {len(plan)} races", extra=log_extra)
    
    # TEMPORARY DEBUG: Log the current logger level
    logger.info(f"DEBUG_SCHEDULER_LOGGER_LEVEL: Logger level is {logger.level} ({logging.getLevelName(logger.level)})", extra=log_extra)

    results = []
    for race_plan in plan:
        r_label = race_plan["r_label"]
        c_label = race_plan["c_label"]
        course_url = race_plan["course_url"]
        date_str = race_plan["date"]
        race_time_local = race_plan["time_local"]

        logger.debug(f"Attempting to enqueue tasks for {r_label}{c_label}", extra=log_extra)

        # H30 task
        h30_task_ok = enqueue_run_task(
            course_url=course_url,
            phase="H30",
            date=date_str,
            race_time_local=race_time_local,
            r_label=r_label,
            c_label=c_label,
            correlation_id=correlation_id,
            trace_id=trace_id,
        ) is not None
        print(f"DEBUG_PRINT: H30 task for {r_label}{c_label} creation {'OK' if h30_task_ok else 'FAILED'}")
        results.append({"phase": "H30", "ok": h30_task_ok})

        # H5 task
        h5_task_ok = enqueue_run_task(
            course_url=course_url,
            phase="H5",
            date=date_str,
            race_time_local=race_time_local,
            r_label=r_label,
            c_label=c_label,
            correlation_id=correlation_id,
            trace_id=trace_id,
        ) is not None
        print(f"DEBUG_PRINT: H5 task for {r_label}{c_label} creation {'OK' if h5_task_ok else 'FAILED'}")
        results.append({"phase": "H5", "ok": h5_task_ok})
    
    print("DEBUG_PRINT: Finished schedule_all_races loop.")
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