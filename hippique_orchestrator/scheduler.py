from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from google.api_core import exceptions as gcp_exceptions
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
import google.auth

from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.time_utils import convert_local_to_utc, format_rfc3339

config = get_config()
logger = get_logger(__name__)

def _generate_task_name(date: str, r_label: str, c_label: str, phase: str) -> str:
    date_compact = date.replace("-", "")
    r_num = r_label[1:].lower()
    c_num = c_label[1:].lower()
    phase_lower = phase.lower().replace("-", "")
    return f"run-{date_compact}-r{r_num}c{c_num}-{phase_lower}"

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
    
    try:
        task_name_short = _generate_task_name(date, r_label, c_label, phase)
        
        creds, inferred_project = google.auth.default()
        
        project_id = config.PROJECT_ID or inferred_project
        location = config.REGION
        queue = config.QUEUE_ID
        
        parent = client.queue_path(project_id, location, queue)
        task_name_full = client.task_path(project_id, location, queue, task_name_short)

        # Idempotency: Check if the task already exists
        try:
            client.get_task(name=task_name_full)
            logger.info(f"Task {task_name_full} already exists. Skipping creation.")
            return task_name_full
        except gcp_exceptions.NotFound:
            pass # Task does not exist, proceed to create it

        # Scheduling logic
        race_datetime_local = datetime.fromisoformat(f"{date}T{race_time_local}")
        snapshot_time_utc = convert_local_to_utc(race_datetime_local) - timedelta(minutes=int(phase[1:]))

        if snapshot_time_utc < datetime.now(timezone.utc):
            logger.warning(f"Skipping task for {task_name_short} as its schedule time {snapshot_time_utc} is in the past.")
            return None

        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(snapshot_time_utc)
        
        payload = {"course_url": course_url, "phase": phase, "date": date, "trace_id": trace_id}
        
        task = {
            "name": task_name_full,
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{config.cloud_run_url}/tasks/run-phase",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode(),
                "oidc_token": {
                    "service_account_email": config.SERVICE_ACCOUNT_EMAIL,
                },
            },
            "schedule_time": timestamp
        }
        logger.critical(f"--- Enqueueing task with parent: {parent} ---", extra=log_extra)
        
        response = client.create_task(parent=parent, task=task)
        logger.info(f"Task created: {response.name}")
        return response.name
        
    except Exception as e:
        logger.error(f"Failed to create task: {e}", exc_info=True, extra=log_extra)
        return None

def schedule_all_races(
    plan: list[dict], mode: str, correlation_id: str, trace_id: str
) -> list[dict[str, Any]]:
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}
    
    try:
        client = tasks_v2.CloudTasksClient()
    except Exception as e:
        logger.error(f"Failed to initialize Cloud Tasks client: {e}", exc_info=True, extra=log_extra)
        return []

    results = []
    for race_plan in plan:
        for phase in ["H30", "H5"]:
            task_ok = enqueue_run_task(
                client=client,
                course_url=race_plan["course_url"],
                phase=phase,
                date=race_plan["date"],
                race_time_local=race_plan["time_local"],
                r_label=race_plan["r_label"],
                c_label=race_plan["c_label"],
                correlation_id=correlation_id,
                trace_id=trace_id,
            ) is not None
            results.append({"phase": phase, "ok": task_ok})
            
    return results