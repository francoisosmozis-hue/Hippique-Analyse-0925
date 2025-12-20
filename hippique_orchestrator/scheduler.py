from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import google.auth
from google.api_core import exceptions as gcp_exceptions
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.time_utils import convert_local_to_utc

config = get_config()
logger = get_logger(__name__)


def _generate_task_name(date: str, r_label: str, c_label: str, phase: str) -> str:
    date_compact = date.replace("-", "")
    r_num = r_label[1:].lower()
    c_num = c_label[1:].lower()
    phase_lower = phase.lower().replace("-", "")
    timestamp = int(datetime.now().timestamp())
    return f"run-{date_compact}-r{r_num}c{c_num}-{phase_lower}-{timestamp}"


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
    print(f"--- In enqueue_run_task for {r_label}{c_label} {phase} ---")
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}

    try:
        task_name_short = _generate_task_name(date, r_label, c_label, phase)

        creds, inferred_project = google.auth.default()

        project_id = config.PROJECT_ID or inferred_project
        location = config.REGION
        queue = config.QUEUE_ID

        parent = client.queue_path(project_id, location, queue)
        task_name_full = client.task_path(project_id, location, queue, task_name_short)

        print("Checking if task exists...")
        # Idempotency: Check if the task already exists
        try:
            client.get_task(name=task_name_full)
            print(f"Task {task_name_full} already exists. Skipping creation.")
            logger.info(f"Task {task_name_full} already exists. Skipping creation.")
            return task_name_full
        except gcp_exceptions.NotFound:
            print("Task does not exist. Proceeding.")
            pass  # Task does not exist, proceed to create it

        # Scheduling logic
        race_datetime_local = datetime.fromisoformat(f"{date}T{race_time_local}")
        snapshot_time_utc = convert_local_to_utc(race_datetime_local) - timedelta(
            minutes=int(phase[1:])
        )
        print(f"Snapshot time (UTC): {snapshot_time_utc}")

        if snapshot_time_utc < datetime.now(timezone.utc):
            print("Snapshot time is in the past. Skipping.")
            logger.warning(
                f"Skipping task for {task_name_short} as its schedule time {snapshot_time_utc} is in the past."
            )
            return None

        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(snapshot_time_utc)

        payload = {"course_url": course_url, "phase": phase, "date": date, "trace_id": trace_id}

        task = {
            "name": task_name_full,
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{config.CLOUD_RUN_URL}/tasks/run-phase",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode(),
                "oidc_token": {
                    "service_account_email": config.SERVICE_ACCOUNT_EMAIL,
                    "audience": config.OIDC_AUDIENCE
                },
            },
            "schedule_time": timestamp,
        }
        print("Creating task...")
        logger.critical(f"--- Enqueueing task with parent: {parent} ---", extra=log_extra)

        response = client.create_task(parent=parent, task=task)
        print(f"Task created: {response.name}")
        logger.info(f"Task created: {response.name}")
        return response.name

    except Exception as e:
        print(f"Failed to create task: {e}")
        logger.error(f"Failed to create task: {e}", exc_info=True, extra=log_extra)
        return None


def schedule_all_races(
    plan: list[dict], mode: str, correlation_id: str, trace_id: str
) -> list[dict[str, Any]]:
    print("--- In schedule_all_races ---")
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}

    try:
        print("Initializing Cloud Tasks client...")
        client = tasks_v2.CloudTasksClient()
        print("Cloud Tasks client initialized.")
    except Exception as e:
        print(f"Failed to initialize Cloud Tasks client: {e}")
        logger.error(
            f"Failed to initialize Cloud Tasks client: {e}", exc_info=True, extra=log_extra
        )
        return []

    results = []
    print(f"Looping through {len(plan)} races...")
    for i, race_plan in enumerate(plan):
        print(f"Race {i+1}/{len(plan)}: {race_plan['r_label']}{race_plan['c_label']}")
        for phase in ["H30", "H5"]:
            print(f"  Phase: {phase}")
            task_ok = (
                enqueue_run_task(
                    client=client,
                    course_url=race_plan["course_url"],
                    phase=phase,
                    date=race_plan["date"],
                    race_time_local=race_plan["time_local"],
                    r_label=race_plan["r_label"],
                    c_label=race_plan["c_label"],
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                )
                is not None
            )
            print(f"  Task OK: {task_ok}")
            results.append({"phase": phase, "ok": task_ok})

    print("--- Exiting schedule_all_races ---")
    return results
