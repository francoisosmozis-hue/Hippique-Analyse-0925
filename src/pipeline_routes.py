"""
src/pipeline_routes.py - Routes for the analysis pipeline
"""

import asyncio
import traceback
from typing import Any, Dict, Optional, Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app_config import get_config
from logging_utils import get_logger
from plan import PlanBuilder
from runner import run_course
from scheduler import schedule_all_races

router = APIRouter()
logger = get_logger(__name__)
config = get_config()

class ScheduleRequest(BaseModel):
    """Request body for POST /schedule"""
    date: str = Field(
        default="today",
        description="Date in YYYY-MM-DD format or 'today'",
        example="2025-10-16"
    )
    mode: str = Field(
        default="tasks",
        description="Scheduling mode: 'tasks' (Cloud Tasks) or 'scheduler' (Cloud Scheduler fallback)",
        example="tasks"
    )

class RunRequest(BaseModel):
    """Request body for POST /run"""
    course_url: str = Field(
        ...,
        description="Full ZEturf course URL",
        example="https://www.zeturf.fr/fr/course/2025-10-16/R1C3-prix-de-vincennes"
    )
    phase: str = Field(
        ...,
        description="Analysis phase: 'H-30', 'H30', 'H-5', or 'H5'",
        example="H30"
    )
    date: str = Field(
        ...,
        description="Race date in YYYY-MM-DD format",
        example="2025-10-16"
    )
    source: Optional[Literal["zeturf", "geny", "boturfers"]] = Field(
        default="boturfers",
        description="Source de données à utiliser (zeturf, geny, boturfers)."
    )

@router.post("/schedule")
async def schedule_daily_plan(request: Request, body: ScheduleRequest):
    correlation_id = request.state.correlation_id
    logger.info("Schedule request received", correlation_id=correlation_id, date=body.date, mode=body.mode)
    try:
        logger.info("Building daily plan...", correlation_id=correlation_id)
        plan = await asyncio.to_thread(PlanBuilder().build_plan, body.date)
        if not plan:
            logger.warning("Empty plan generated", correlation_id=correlation_id)
            return {"ok": False, "error": "No races found for this date", "date": body.date, "correlation_id": correlation_id}
        logger.info(f"Plan built: {len(plan)} races", correlation_id=correlation_id, total_races=len(plan))
        logger.info("Scheduling Cloud Tasks...", correlation_id=correlation_id)
        scheduled = schedule_all_races(plan=plan)
        success_h30 = sum(1 for s in scheduled['tasks'] if s["h30_task"])
        success_h5 = sum(1 for s in scheduled['tasks'] if s["h5_task"])
        logger.info("Scheduling complete", correlation_id=correlation_id, total=len(plan), success_h30=success_h30, success_h5=success_h5)
        plan_summary = [{"race": f"{p['r_label']}{p['c_label']}", "time": p["time_local"], "meeting": p.get("meeting", ""), "url": p["course_url"]} for p in plan[:5]]
        return {"ok": True, "date": body.date, "total_races": len(plan), "scheduled_h30": success_h30, "scheduled_h5": success_h5, "mode": body.mode, "plan_summary": plan_summary, "scheduled_details": scheduled, "correlation_id": correlation_id}
    except Exception as e:
        logger.error(f"Schedule failed: {e}", correlation_id=correlation_id, exc_info=e)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"ok": False, "error": str(e), "traceback": traceback.format_exc(), "correlation_id": correlation_id})

@router.post("/run")
async def run_race_analysis(request: Request, body: RunRequest):
    correlation_id = request.state.correlation_id
    logger.info("Run request received", correlation_id=correlation_id, course_url=body.course_url, phase=body.phase, date=body.date, source=body.source)
    try:
        result = run_course(course_url=body.course_url, phase=body.phase, date=body.date, source=body.source)
        result["correlation_id"] = correlation_id
        if result.get("ok"):
            logger.info("Run complete", correlation_id=correlation_id, phase=result.get("phase"), artifacts_count=len(result.get("artifacts", [])))
        else:
            logger.error("Run failed", correlation_id=correlation_id, error=result.get("error"), returncode=result.get("returncode"))
        status_code = status.HTTP_200_OK if result.get("ok") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=result)
    except Exception as e:
        logger.error(f"Run failed with exception: {e}", correlation_id=correlation_id, exc_info=e)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"ok": False, "error": str(e), "traceback": traceback.format_exc(), "correlation_id": correlation_id})