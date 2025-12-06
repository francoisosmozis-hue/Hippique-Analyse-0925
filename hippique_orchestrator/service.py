"""
src/service.py - FastAPI Service Principal

Service Cloud Run orchestrant l'analyse hippique quotidienne.
"""

from __future__ import annotations

import asyncio
import traceback
import uuid
from datetime import datetime
from typing import Any
import os

from fastapi import FastAPI, Request, Response, HTTPException, status, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.plan import build_plan_async
from hippique_orchestrator.scheduler import schedule_all_races
from hippique_orchestrator.snapshot_manager import write_snapshot_for_day
from hippique_orchestrator.runner import run_course
from hippique_orchestrator import firestore_client, time_utils

# ============================================
# Configuration
# ============================================

logger = get_logger(__name__)
config = get_config()

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")

app = FastAPI(
    title="Hippique Orchestrator",
    description="Cloud Run service for automated horse racing analysis (GPI v5.2)",
    version="2.1.0",
)

app.mount("/pronostics", StaticFiles(directory=STATIC_DIR, html=True), name="pronostics")

# ============================================
# Request/Response Models
# ============================================

class ScheduleRequest(BaseModel):
    date: str = Field("today", description="Date in YYYY-MM-DD format or 'today'")
    mode: str = Field("tasks", description="Scheduling mode: 'tasks' or 'scheduler'")

class RunRequest(BaseModel):
    course_url: str = Field(..., description="Full course URL")
    phase: str = Field(..., description="Analysis phase: 'H-30', 'H-5', etc.")
    date: str = Field(..., description="Race date in YYYY-MM-DD format")
    trace_id: str | None = None

# ============================================
# Middleware
# ============================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    
    logger.info(f"{request.method} {request.url.path}", extra={"correlation_id": correlation_id})
    
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    except Exception as e:
        logger.error(f"Request failed: {e}", extra={"correlation_id": correlation_id, "exc_info": e})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error", "correlation_id": correlation_id},
            headers={"X-Correlation-ID": correlation_id},
        )

# ============================================
# Endpoints
# ============================================

@app.get("/ping")
async def ping():
    return {"status": "pong"}

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy",
        "service": "hippique-orchestrator",
        "version": "2.1.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

@app.post("/schedule", status_code=status.HTTP_202_ACCEPTED)
async def schedule_daily_plan(request: Request, body: ScheduleRequest):
    correlation_id = request.state.correlation_id
    trace_id = str(uuid.uuid4())
    logger.info("Schedule request received", extra={"correlation_id": correlation_id, "trace_id": trace_id, "date": body.date, "mode": body.mode})
    
    try:
        plan = await build_plan_async(body.date)
        if not plan:
            logger.warning("Empty plan generated", extra={"correlation_id": correlation_id, "trace_id": trace_id})
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"ok": False, "error": "No races found for this date"})
        
        logger.info(f"Plan built: {len(plan)} races", extra={"correlation_id": correlation_id, "trace_id": trace_id})
        
        scheduled = schedule_all_races(plan=plan, mode=body.mode, correlation_id=correlation_id, trace_id=trace_id)
        
        success_h30 = sum(1 for s in scheduled if s["phase"] == "H30" and s["ok"])
        success_h5 = sum(1 for s in scheduled if s["phase"] == "H5" and s["ok"])
        all_ok = all(s["ok"] for s in scheduled)

        logger.info("Scheduling complete", extra={"correlation_id": correlation_id, "trace_id": trace_id, "success_h30": success_h30, "success_h5": success_h5})

        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={
            "ok": all_ok, "date": body.date, "total_races": len(plan),
            "scheduled_h30": success_h30, "scheduled_h5": success_h5,
            "mode": body.mode, "correlation_id": correlation_id, "trace_id": trace_id,
        })
    except Exception as e:
        logger.error(f"Schedule failed: {e}", extra={"correlation_id": correlation_id, "trace_id": trace_id, "exc_info": e})
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"ok": False, "error": str(e)})


@app.post("/run")
async def run_race_analysis(request: Request, body: RunRequest):
    correlation_id = request.state.correlation_id
    trace_id = body.trace_id or correlation_id
    logger.info("Run request received", extra={"correlation_id": correlation_id, "trace_id": trace_id, "course_url": body.course_url, "phase": body.phase})
    
    try:
        result = run_course(course_url=body.course_url, phase=body.phase, date=body.date, correlation_id=correlation_id, trace_id=trace_id)
        result["correlation_id"] = correlation_id
        result["trace_id"] = trace_id
        
        status_code = status.HTTP_200_OK if result.get("ok") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=result)
    except Exception as e:
        logger.error(f"Run failed with exception: {e}", extra={"correlation_id": correlation_id, "trace_id": trace_id, "exc_info": e})
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"ok": False, "error": str(e)})

# ============================================
# Task Endpoints (for Cloud Tasks)
# ============================================

@app.post("/tasks/bootstrap-day", status_code=status.HTTP_202_ACCEPTED)
async def tasks_bootstrap_day(request: Request, body: ScheduleRequest, background_tasks: BackgroundTasks):
    correlation_id = request.state.correlation_id
    trace_id = str(uuid.uuid4())
    logger.info("Bootstrap day task received", extra={"correlation_id": correlation_id, "trace_id": trace_id, "date": body.date})
    
    background_tasks.add_task(bootstrap_day_pipeline, date_str=body.date, correlation_id=correlation_id, trace_id=trace_id)
    
    return {"ok": True, "message": f"Bootstrap for {body.date} initiated in background."}

@app.post("/tasks/run-phase", status_code=status.HTTP_200_OK)
async def tasks_run_phase(request: Request, body: RunRequest):
    correlation_id = request.state.correlation_id
    trace_id = body.trace_id or correlation_id
    logger.info(f"Run phase task received for course: {body.course_url}", extra={"correlation_id": correlation_id, "trace_id": trace_id})
    
    result = run_course(course_url=body.course_url, phase=body.phase, date=body.date, correlation_id=correlation_id, trace_id=trace_id)
    
    return {"ok": result.get("ok", False), "phase": result.get("phase"), "artifacts": result.get("artifacts", [])}

# ============================================
# API & Debug Endpoints
# ============================================

@app.get("/api/pronostics")
async def get_pronostics(date: str = Query(..., description="Date in YYYY-MM-DD format")):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date format. Please use YYYY-MM-DD.")

    correlation_id = str(uuid.uuid4())
    logger.info(f"Fetching pronostics for date: {date} from Firestore", extra={"correlation_id": correlation_id})

    try:
        race_documents = firestore_client.get_races_by_date_prefix(date)
        
        all_pronostics = []
        for doc in race_documents:
            analysis = doc.get("tickets_analysis")
            if analysis:
                all_pronostics.append({
                    "rc": doc.get("rc", "N/A"),
                    "gpi_decision": analysis.get("gpi_decision", "N/A"),
                    "tickets": analysis.get("tickets", [])
                })
        
        return {"ok": True, "total_races": len(all_pronostics), "date": date, "pronostics": all_pronostics}
    except Exception as e:
        logger.error(f"Error fetching pronostics from Firestore: {e}", extra={"correlation_id": correlation_id, "exc_info": e})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch pronostics from Firestore.")

@app.get("/debug/parse")
async def debug_parse(date: str = "2025-10-17"):
    result = await build_plan_async(date)
    return {"ok": True, "date": date, "count": len(result), "races": result[:3] if result else []}

# ============================================
# Core Logic (used by startup and endpoints)
# ============================================

async def bootstrap_day_pipeline(date_str: str, correlation_id: str, trace_id: str) -> dict[str, Any] | None:
    """Builds the plan for the day and schedules all races."""
    logger.info(f"Starting bootstrap pipeline for {date_str}", extra={"correlation_id": correlation_id, "trace_id": trace_id})
    plan = await build_plan_async(date_str)
    if not plan:
        logger.warning(f"No plan built for {date_str}. Aborting bootstrap.", extra={"correlation_id": correlation_id, "trace_id": trace_id})
        return None
    
    logger.info(f"Plan built with {len(plan)} races. Now scheduling tasks.", extra={"correlation_id": correlation_id, "trace_id": trace_id})
    schedule_all_races(plan=plan, mode="tasks", correlation_id=correlation_id, trace_id=trace_id)
    return {"races_count": len(plan), "races": plan}

async def run_bootstrap_if_needed():
    """
    Checks if the daily planning has been done and runs it if not.
    This provides resilience against failed scheduler triggers.
    """
    await asyncio.sleep(10) # Wait a bit for other services to be ready if needed
    
    today_str = time_utils.get_today_str()
    correlation_id = str(uuid.uuid4())
    log_extra = {"correlation_id": correlation_id, "trace_id": correlation_id, "date": today_str}

    logger.info("Startup check: Verifying if daily planning is needed.", extra=log_extra)

    if firestore_client.is_day_planned(today_str):
        logger.info(f"Daily planning for {today_str} already completed. Startup check passed.", extra=log_extra)
        return

    logger.warning(f"Daily planning for {today_str} not found. Starting bootstrap process now.", extra=log_extra)
    
    try:
        plan_details = await bootstrap_day_pipeline(date_str=today_str, correlation_id=correlation_id, trace_id=correlation_id)
        if plan_details:
            firestore_client.mark_day_as_planned(today_str, {
                "created_at": datetime.now(time_utils.get_tz()).isoformat(),
                "races_count": plan_details.get("races_count", 0),
                "correlation_id": correlation_id
            })
            logger.info(f"Successfully completed bootstrap for {today_str} on startup.", extra=log_extra)
    except Exception as e:
        logger.error(f"Startup bootstrap process for {today_str} failed: {e}", extra=log_extra, exc_info=True)


# ============================================
# Startup/Shutdown Events
# ============================================

@app.on_event("startup")
async def startup_event():
    logger.info("Service starting", extra={"version": "2.1.0", "project_id": config.PROJECT_ID})
    asyncio.create_task(run_bootstrap_if_needed())

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Service shutting down")