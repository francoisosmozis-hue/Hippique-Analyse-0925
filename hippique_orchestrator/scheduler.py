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


def _get_and_normalize_queue_path(
    client: tasks_v2.CloudTasksClient, queue_id_raw: str
) -> tuple[str, str, str, str]:
    """
    Parses a queue ID (short name or full path) and returns normalized parts.

    Returns:
        A tuple of (project, location, queue_name, full_queue_path).
    """
    if "projects/" in queue_id_raw:
        # If the full path is provided, parse it
        try:
            project, location, queue_name = client.parse_queue_path(queue_id_raw)[
                "project"
            ], client.parse_queue_path(queue_id_raw)["location"], client.parse_queue_path(
                queue_id_raw
            )["queue"]
            full_queue_path = queue_id_raw
            return project, location, queue_name, full_queue_path
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid full queue path provided: {queue_id_raw}") from e
    else:
        # If short name, construct the full path from config/inferred project
        _, inferred_project = google.auth.default()
        project = config.PROJECT_ID or inferred_project
        location = config.REGION
        queue_name = queue_id_raw
        if not all([project, location, queue_name]):
            raise ValueError(
                f"Cannot construct queue path from incomplete parts: project={project}, location={location}, queue={queue_name}"
            )
        full_queue_path = client.queue_path(project, location, queue_name)
        return project, location, queue_name, full_queue_path


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
    schedule_time_utc: datetime | None = None,
) -> str | None:
    """Crée une Cloud Task pour exécuter une analyse de course."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}
    logger.info(f"--- In enqueue_run_task for {r_label}{c_label} {phase} ---", extra=log_extra)

    try:
        project_id, location, queue_name, parent_path = _get_and_normalize_queue_path(
            client, config.QUEUE_ID
        )

        # Optional: In debug mode, check if queue exists to get a clearer error
        if config.DEBUG:
            try:
                client.get_queue(name=parent_path)
                logger.info(f"Queue check PASSED for {parent_path}", extra=log_extra)
            except gcp_exceptions.NotFound:
                logger.error(
                    f"Queue check FAILED: Queue '{parent_path}' not found.",
                    extra=log_extra,
                )
                # Fail fast if queue doesn't exist
                return None

        # Use provided schedule time or calculate H-30/H-5
        if schedule_time_utc is None:
            race_datetime_local = datetime.fromisoformat(f"{date}T{race_time_local}")
            schedule_time_utc = convert_local_to_utc(race_datetime_local) - timedelta(
                minutes=int(phase[1:])
            )

        logger.info(f"Calculated schedule time (UTC): {schedule_time_utc}", extra=log_extra)

        if schedule_time_utc < datetime.now(timezone.utc):
            logger.warning(
                f"Skipping task for {r_label}{c_label} as its schedule time {schedule_time_utc} is in the past."
            )
            return None

        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(schedule_time_utc)

        payload = {"course_url": course_url, "phase": phase, "date": date, "trace_id": trace_id}
        target_url = f"{config.CLOUD_RUN_URL}/tasks/run-phase"

        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": target_url,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode(),
                "oidc_token": {
                    "service_account_email": config.SERVICE_ACCOUNT_EMAIL,
                    "audience": config.OIDC_AUDIENCE,
                },
            },
            "schedule_time": timestamp,
        }

        # Log all details just before the API call
        log_details = {
            "project_id": project_id,
            "location": location,
            "queue_id_raw": config.QUEUE_ID,
            "parent_path": parent_path,
            "target_url": target_url,
            "client_endpoint": client._transport._host,
        }
        logger.info("--- PREPARING TO CREATE TASK ---", extra={**log_extra, **log_details})

        response = client.create_task(parent=parent_path, task=task)
        logger.info(f"Task created: {response.name}", extra=log_extra)
        return response.name

    except Exception as e:
        logger.error(f"Failed to create task: {e}", exc_info=True, extra=log_extra)
        return None


def schedule_all_races(
    plan: list[dict], mode: str, correlation_id: str, trace_id: str
) -> list[dict[str, Any]]:
    logger.info("--- In schedule_all_races ---", extra={"correlation_id": correlation_id})

    try:
        logger.info("Initializing Cloud Tasks client...")
        client = tasks_v2.CloudTasksClient()
        logger.info("Cloud Tasks client initialized.")
    except Exception as e:
        logger.error(
            f"Failed to initialize Cloud Tasks client: {e}",
            exc_info=True,
            extra={"correlation_id": correlation_id},
        )
        return []

    results = []
    logger.info(f"Looping through {len(plan)} races...", extra={"correlation_id": correlation_id})
    for i, race_plan in enumerate(plan):
        logger.debug(
            f"Race {i+1}/{len(plan)}: {race_plan['r_label']}{race_plan['c_label']}",
            extra={"correlation_id": correlation_id},
        )
        for phase in ["H30", "H5"]:
            logger.debug(f"  Phase: {phase}", extra={"correlation_id": correlation_id})
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
            results.append({"phase": phase, "ok": task_ok})

    logger.info("--- Exiting schedule_all_races ---", extra={"correlation_id": correlation_id})
    return results
