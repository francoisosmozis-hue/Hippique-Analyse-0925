from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import google.auth
from google.cloud import tasks_v2
from google.api_core import exceptions as gexc
from google.protobuf import timestamp_pb2

from hippique_orchestrator import config
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.time_utils import convert_local_to_utc

logger = get_logger(__name__)


def _calculate_task_schedule(
    race_time_local: str, date: str, phase: str, force: bool
) -> dict[str, Any]:
    """
    Calculates the UTC schedule time for a task and determines if it should be skipped.

    Returns:
        A dictionary containing the status, schedule time, and a reason.
    """
    if force:
        schedule_time_utc = datetime.now(timezone.utc) + timedelta(minutes=2)
        reason = f"Forced schedule to now + 2 minutes: {schedule_time_utc.isoformat()}"
        logger.info(f"[Force Mode] {reason}")
        return {"status": "candidate", "schedule_time_utc": schedule_time_utc, "reason": reason}

    try:
        phase_minutes = int(phase[1:])
        race_datetime_local = datetime.fromisoformat(f"{date}T{race_time_local}")
        schedule_time_utc = convert_local_to_utc(race_datetime_local) - timedelta(
            minutes=phase_minutes
        )

        if schedule_time_utc < datetime.now(timezone.utc):
            reason = f"Schedule time {schedule_time_utc.isoformat()} is in the past."
            logger.warning(f"Skipping task: {reason}")
            return {"status": "skipped", "schedule_time_utc": schedule_time_utc, "reason": reason}

        reason = f"Calculated schedule time (UTC): {schedule_time_utc.isoformat()}"
        return {"status": "candidate", "schedule_time_utc": schedule_time_utc, "reason": reason}

    except Exception as e:
        reason = f"Error calculating schedule time: {e}"
        logger.error(reason, exc_info=True)
        return {"status": "skipped", "schedule_time_utc": None, "reason": reason}


def enqueue_run_task(
    client: tasks_v2.CloudTasksClient,
    course_url: str,
    phase: str,
    date: str,
    schedule_time_utc: datetime,
) -> tuple[bool, str | None]:
    """
    Crée une Cloud Task et retourne un tuple (succès, résultat).
    Le résultat est le nom de la tâche en cas de succès, ou un message d'erreur.
    """
    logger.debug(f"Preparing to enqueue task for {course_url} at {schedule_time_utc}")
    try:
        _, project_id = google.auth.default()
        parent_path = client.queue_path(
            project_id or config.PROJECT_ID, config.LOCATION, config.TASK_QUEUE
        )

        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(schedule_time_utc)

        doc_id = None
        if r_label and c_label:
            doc_id = f"{date}_{r_label}{c_label}"
        payload = {
            "course_url": course_url,
            "phase": phase,
            "date": date,
            "r_label": r_label,
            "c_label": c_label,
            "doc_id": doc_id,
        }
        service_url = config.get_service_url()
        if not service_url:
            return False, "Service URL is not configured. Cannot create task."
            
        target_url = f"{service_url}/tasks/run-phase"

        http_request = {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": target_url,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload).encode(),
        }

        if config.REQUIRE_AUTH:
            if not config.TASK_OIDC_SA_EMAIL:
                raise ValueError("TASK_OIDC_SA_EMAIL must be set when REQUIRE_AUTH is True.")
            oidc_token = {
                "service_account_email": config.TASK_OIDC_SA_EMAIL,
                "audience": service_url,
            }
            http_request["oidc_token"] = oidc_token

        task = {"http_request": http_request, "schedule_time": timestamp}
        
        logger.info(
            "Enqueuing Cloud Task",
            extra={
                "task_payload": payload,
                "target_url": target_url,
                "schedule_time_utc": schedule_time_utc.isoformat(),
                "oidc_enabled": "oidc_token" in http_request,
            },
        )
        
        response = client.create_task(parent=parent_path, task=task)
        logger.info(f"Task created: {response.name}")
        return True, response.name

    except gexc.PermissionDenied as e:
        sa_email = config.TASK_OIDC_SA_EMAIL or "the service account of this Cloud Run service"
        error_msg = (
            f"Permission denied to create Cloud Task. "
            f"Please grant 'roles/cloudtasks.enqueuer' to '{sa_email}'. "
            f"Original error: {e}"
        )
        logger.critical(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Failed to create task for {course_url}: {e}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def schedule_all_races(
    plan: list[dict], force: bool = False, dry_run: bool = False
) -> list[dict[str, Any]]:
    logger.info(f"--- Starting schedule_all_races (Force: {force}, Dry Run: {dry_run}) ---")

    candidate_tasks = []
    results = []

    for race_plan in plan:
        for phase in ["H30", "H5"]:
            task_info = {
                "race": f"{race_plan['r_label']}{race_plan['c_label']}",
                    "r_label": race_plan["r_label"],
                    "c_label": race_plan["c_label"],
                "phase": phase,
                "course_url": race_plan["course_url"],
                "date": race_plan["date"],
            }
            schedule_details = _calculate_task_schedule(
                race_time_local=race_plan["time_local"],
                date=race_plan["date"],
                phase=phase,
                force=force,
            )
            task_info.update(schedule_details)

            if task_info["status"] == "candidate":
                candidate_tasks.append(task_info)
            else:
                results.append({
                    "race": task_info["race"],
                    "phase": task_info["phase"],
                    "task_name": None,
                    "ok": False,
                    "reason": task_info.get("reason"),
                })
    
    logger.info(f"Calculation complete. Candidates: {len(candidate_tasks)}, Skipped: {len(results)}")

    if dry_run:
        logger.info("--- Dry run complete. Returning calculated tasks. ---")
        # For dry run, we just show what would be scheduled
        return [
            {**task, "ok": True, "task_name": "dry_run_candidate"}
            for task in candidate_tasks
        ] + results

    logger.info("--- Executing real run. Initializing Cloud Tasks client. ---")
    try:
        client = tasks_v2.CloudTasksClient()
    except Exception as e:
        logger.critical(f"Failed to initialize Cloud Tasks client: {e}", exc_info=True)
        # If client fails, all candidates fail
        for task in candidate_tasks:
            results.append({
                "race": task["race"], "phase": task["phase"], "task_name": None,
                "ok": False, "reason": f"Failed to init CloudTasks client: {e}",
            })
        return results

    for task in candidate_tasks:
        success, result = enqueue_run_task(
            client=client,
            course_url=task["course_url"],
            phase=task["phase"],
            date=task["date"],
            schedule_time_utc=task["schedule_time_utc"],
            r_label=task.get("r_label"),
            c_label=task.get("c_label"),
        )
        results.append({
            "race": task["race"],
            "phase": task["phase"],
            "task_name": result if success else None,
            "ok": success,
            "reason": None if success else result,
        })

    logger.info("--- schedule_all_races complete. ---")
    # Sort results to have a consistent order
    return sorted(results, key=lambda x: (x["race"], x["phase"]))
