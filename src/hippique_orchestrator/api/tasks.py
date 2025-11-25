"""
src/api/tasks.py - FastAPI Router pour les tâches internes d'orchestration.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from hippique_orchestrator.app_config import get_config
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.snapshot_manager import write_snapshot_for_day
from hippique_orchestrator.runner import run_course # For /tasks/run-phase
from hippique_orchestrator.plan import build_plan_async # For /tasks/bootstrap-day
from hippique_orchestrator.scheduler import enqueue_run_task # Use existing enqueue_run_task

router = APIRouter(prefix="/tasks", tags=["Tasks"])
config = get_config()
logger = get_logger(__name__)

# ============================================
# Request Models (as per specification)
# ============================================

class Snapshot9hRequest(BaseModel):
    """Request body for POST /tasks/snapshot-9h"""
    date: Optional[str] = Field(
        default=None,
        description="Date in YYYY-MM-DD format. Defaults to today.",
        example="2025-11-22"
    )
    meeting_urls: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific meeting URLs to snapshot.",
    )

class RunPhaseRequest(BaseModel):
    """Request body for POST /tasks/run-phase"""
    course_url: str = Field(
        ...,
        description="Full ZEturf course URL",
        example="https://www.zeturf.fr/fr/course/2025-11-22/R1C1-prix-de-la-ville"
    )
    phase: str = Field(
        ...,
        description="Analysis phase: 'H9', 'H30', or 'H5'",
        example="H30"
    )
    date: str = Field(
        ...,
        description="Race date in YYYY-MM-DD format",
        example="2025-11-22"
    )

class BootstrapDayRequest(BaseModel):
    """Request body for POST /tasks/bootstrap-day"""
    date: Optional[str] = Field(
        default=None,
        description="Date in YYYY-MM-DD format. Defaults to today.",
        example="2025-11-22"
    )

# ============================================
# Endpoints
# ============================================

@router.post("/snapshot-9h", status_code=status.HTTP_202_ACCEPTED)
async def snapshot_9h_task(request: Request, body: Snapshot9hRequest, background_tasks: BackgroundTasks):
    """
    Triggers the 'H9' snapshot for all French races of the day.
    This is intended to be called by Cloud Scheduler at 9 AM.
    """
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    
    target_date_str = body.date if body.date else datetime.now().strftime("%Y-%m-%d")

    logger.info(
        f"Received request for H9 snapshot for {target_date_str}",
        extra={"correlation_id": correlation_id, "date": target_date_str},
    )

    # The actual snapshot logic runs in the background to avoid HTTP timeouts
    background_tasks.add_task(
        write_snapshot_for_day,
        date_str=target_date_str,
        race_urls=body.meeting_urls, # Pass meeting_urls if provided
        rc_labels=None, # rc_labels cannot be easily derived if meeting_urls are provided
        phase="H9",
        correlation_id=correlation_id,
    )

    return {
        "ok": True,
        "message": f"H9 snapshot for {target_date_str} initiated in background.",
        "date": target_date_str,
        "correlation_id": correlation_id,
    }

@router.post("/run-phase", status_code=status.HTTP_200_OK)
async def run_phase_task(request: Request, body: RunPhaseRequest):
    """
    Executes the analysis for a single race for a given phase (H9, H30, H5).
    This endpoint is the target for Cloud Tasks.
    """
    correlation_id = getattr(request.state, "correlation_id", "N/A")

    logger.info(
        f"Received run-phase request for {body.course_url} (phase: {body.phase})",
        extra={"correlation_id": correlation_id, "course_url": body.course_url, "phase": body.phase, "date": body.date},
    )

    try:
        # Re-using the existing run_course function from the project's core logic
        result = run_course(
            course_url=body.course_url,
            phase=body.phase,
            date=body.date,
            correlation_id=correlation_id,
        )
        result["correlation_id"] = correlation_id
        
        if not result.get("ok"):
            logger.error(
                f"Run phase failed for {body.course_url} (phase: {body.phase})",
                extra={"correlation_id": correlation_id, "error": result.get("error")},
            )
            # Return a 500 error but with the structured error message from the runner
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=result,
            )
        
        logger.info(
            f"Run phase completed successfully for {body.course_url} (phase: {body.phase})",
            extra={"correlation_id": correlation_id},
        )
        return result

    except Exception as e:
        logger.error(
            f"Exception during run-phase for {body.course_url} (phase: {body.phase}): {e}",
            exc_info=True,
            extra={"correlation_id": correlation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {e}",
        )

@router.post("/bootstrap-day", status_code=status.HTTP_202_ACCEPTED)
async def bootstrap_day_task(request: Request, body: BootstrapDayRequest):
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
        logger.info(f"Building daily plan for {target_date_str}...", extra={"correlation_id": correlation_id})
        plan = await build_plan_async(target_date_str)
        
        if not plan:
            logger.warning(f"Empty plan for {target_date_str}. No tasks to schedule.", extra={"correlation_id": correlation_id})
            # Use a 404 response to indicate no races were found
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"ok": False, "error": "No races found for this date", "date": target_date_str, "correlation_id": correlation_id}
            )
        
        logger.info(f"Plan built: {len(plan)} races for {target_date_str}.", extra={"correlation_id": correlation_id, "num_races": len(plan)})

        # 2. Schedule tasks for each race
        scheduled_tasks_count = 0
        for race in plan:
            race_datetime_str = f"{target_date_str} {race['time_local']}"
            race_datetime = datetime.strptime(race_datetime_str, "%Y-%m-%d %H:%M")

            # Schedule H-30 task
            h30_datetime = race_datetime - config.h30_offset
            if h30_datetime > datetime.now():
                enqueue_run_task(
                    course_url=race["course_url"], phase="H30", date=target_date_str,
                    race_time_local=race["time_local"], r_label=race["r_label"], c_label=race["c_label"],
                    correlation_id=correlation_id
                )
                scheduled_tasks_count += 1

            # Schedule H-5 task
            h5_datetime = race_datetime - config.h5_offset
            if h5_datetime > datetime.now():
                enqueue_run_task(
                    course_url=race["course_url"], phase="H5", date=target_date_str,
                    race_time_local=race["time_local"], r_label=race["r_label"], c_label=race["c_label"],
                    correlation_id=correlation_id
                )
                scheduled_tasks_count += 1
        
        logger.info(f"Bootstrap day completed. Scheduled {scheduled_tasks_count} tasks.", extra={"correlation_id": correlation_id})
        return {
            "ok": True,
            "message": f"Bootstrap for {target_date_str} initiated. {scheduled_tasks_count} tasks scheduled.",
            "date": target_date_str,
            "total_races": len(plan),
            "scheduled_tasks": scheduled_tasks_count,
            "correlation_id": correlation_id,
        }

    except Exception as e:
        logger.error(f"Exception during bootstrap-day for {target_date_str}: {e}", exc_info=True, extra={"correlation_id": correlation_id})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error during bootstrap: {e}")
