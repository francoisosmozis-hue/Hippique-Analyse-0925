"""
src/api/tasks.py - FastAPI Router pour les tâches internes d'orchestration.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from starlette.concurrency import run_in_threadpool

from hippique_orchestrator import config, firestore_client, scheduler
from hippique_orchestrator.auth import verify_oidc_token
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.plan import build_plan_async
from hippique_orchestrator.runner import run_course

from hippique_orchestrator.schemas import BootstrapDayRequest, RunPhaseRequest, Snapshot9HRequest
from hippique_orchestrator.snapshot_manager import (
    write_snapshot_for_day_async,  # Added this import
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])

logger = get_logger(__name__)

OIDC_TOKEN_DEPENDENCY = Depends(verify_oidc_token)

# ... (rest of the file remains the same until run_phase_task)


@router.post("/run-phase", status_code=status.HTTP_200_OK)
async def run_phase_task(
    request: Request,
    body: RunPhaseRequest,
    token_claims: dict = OIDC_TOKEN_DEPENDENCY,
):
    """
    Executes the analysis for a single race for a given phase (H9, H30, H5).
    This endpoint is the target for Cloud Tasks.
    """
    correlation_id = getattr(request.state, "correlation_id", "N/A")

    logger.info(
        f"Received run-phase request for {body.course_url} (phase: {body.phase})",
        extra={
            "correlation_id": correlation_id,
            "course_url": body.course_url,
            "phase": body.phase,
            "date": body.date,
        },
    )
    doc_id = body.doc_id or firestore_client.get_doc_id_from_url(body.course_url, body.date)
    if not doc_id:
        raise HTTPException(status_code=422, detail="Cannot determine doc_id (missing doc_id and unparseable URL).")

    try:
        analysis_result = await run_course(
            course_url=body.course_url,
            phase=body.phase,
            date=body.date,
            correlation_id=correlation_id,
        )
        final_result = dict(analysis_result)
        final_result["correlation_id"] = correlation_id

        await run_in_threadpool(firestore_client.update_race_document, doc_id, final_result)

        logger.info(
            f"Run phase completed successfully for {body.course_url} (phase: {body.phase})",
            extra={"correlation_id": correlation_id},
        )
        return final_result

    except Exception as e:
        logger.error(
            (f"Exception during run-phase for {body.course_url} (phase: {body.phase}): {e}"),
            exc_info=True,
            extra={"correlation_id": correlation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {e}",
        ) from e


@router.post("/snapshot-9h", status_code=status.HTTP_200_OK)
async def snapshot_9h_task(
    request: Request,
    body: Snapshot9HRequest,  # Now using the specific Snapshot9HRequest
    token_claims: dict = OIDC_TOKEN_DEPENDENCY,
):
    """
    Triggers an H9 snapshot for the specified date and meeting URLs.
    """
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    target_date_str = body.date if body.date else datetime.now().strftime("%Y-%m-%d")

    logger.info(
        f"Received snapshot-9h request for {target_date_str} with URLs: {body.meeting_urls}, RC Labels: {body.rc_labels}",
        extra={
            "correlation_id": correlation_id,
            "date": target_date_str,
            "meeting_urls": body.meeting_urls,
            "rc_labels": body.rc_labels,
        },
    )

    try:
        # Call the existing snapshot writing logic
        await write_snapshot_for_day_async(
            date_str=target_date_str,
            phase="H9",  # Explicitly passing the phase
            race_urls=body.meeting_urls,
            rc_labels=body.rc_labels,
            correlation_id=correlation_id,
        )

        logger.info(
            f"Snapshot-9h completed successfully for {target_date_str}.",
            extra={"correlation_id": correlation_id, "date": target_date_str},
        )
        return {
            "ok": True,
            "message": f"Snapshot-9h for {target_date_str} initiated.",
            "date": target_date_str,
            "correlation_id": correlation_id,
        }
    except Exception as e:
        logger.error(
            f"Exception during snapshot-9h for {target_date_str}: {e}",
            exc_info=True,
            extra={"correlation_id": correlation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during snapshot-9h: {e}",
        ) from e


@router.post("/bootstrap-day", status_code=status.HTTP_200_OK)
async def bootstrap_day_task(
    request: Request,
    body: BootstrapDayRequest,
    token_claims: dict = OIDC_TOKEN_DEPENDENCY,
):
    """
    Reads the day's plan, and for each race, creates two Cloud Tasks (H-30, H-5)
    to call /tasks/run-phase at the appropriate times.
    """
    correlation_id = getattr(request.state, "correlation_id", "N/A")

    target_date_str = body.date if body.date else datetime.now().strftime("%Y-%m-%d")

    logger.info(
        f"Received request to bootstrap day {target_date_str}",
        extra={"correlation_id": correlation_id, "date": target_date_str},
    )

    try:
        # 1. Build the daily race plan
        logger.info(
            f"Building daily plan for {target_date_str}...",
            extra={"correlation_id": correlation_id},
        )
        plan = await build_plan_async(target_date_str)

        if not plan:
            logger.warning(
                f"Empty plan for {target_date_str}. No tasks to schedule.",
                extra={"correlation_id": correlation_id},
            )
            # Use a 404 response to indicate no races were found
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "ok": False,
                    "error": "No races found for this date",
                    "date": target_date_str,
                    "correlation_id": correlation_id,
                },
            )

        logger.info(
            f"Plan built: {len(plan)} races for {target_date_str}.",
            extra={"correlation_id": correlation_id, "num_races": len(plan)},
        )

        # Delegate to the canonical scheduler (single source of truth)
        service_url = f"{request.url.scheme}://{request.url.netloc}"
        results = await run_in_threadpool(
            scheduler.schedule_all_races,
            plan,
            service_url,
            False,  # force
            False,  # dry_run
        )
        ok_count = sum(1 for r in results if r.get("ok"))
        return {
            "ok": True,
            "message": f"Bootstrap for {target_date_str} done: {ok_count}/{len(results)} tasks scheduled.",
            "date": target_date_str,
            "details": results,
            "correlation_id": correlation_id,
        }

    except Exception as e:
        logger.error(
            f"Exception during bootstrap-day for {target_date_str}: {e}",
            exc_info=True,
            extra={"correlation_id": correlation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during bootstrap: {e}",
        ) from e
