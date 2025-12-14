"""
src/service.py - FastAPI Service Principal

Service Cloud Run orchestrant l'analyse hippique quotidienne.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from hippique_orchestrator import firestore_client, time_utils
from hippique_orchestrator.auth import auth_middleware
from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.plan import build_plan_async
from hippique_orchestrator.runner import run_course
from hippique_orchestrator.scheduler import schedule_all_races

# ============================================
# Configuration
# ============================================

logger = get_logger(__name__)
config = get_config()

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
templates = Jinja2Templates(directory="templates")


app = FastAPI(
    title="Hippique Orchestrator",
    description="Cloud Run service for automated horse racing analysis (GPI v5.2)",
    version="2.1.0",
)

app.include_router(api_router)

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

# The auth middleware is placed here but applied selectively based on path
app.middleware("http")(auth_middleware)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))

    try:
        response = await call_next(request)
        logger.info(f"{request.method} {request.url.path}", extra={"correlation_id": correlation_id, "status_code": response.status_code})
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    except Exception as e:
        logger.error(f"Request failed: {e}", exc_info=True, extra={"correlation_id": correlation_id})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error", "correlation_id": correlation_id},
            headers={"X-Correlation-ID": correlation_id},
        )

# ============================================
# API Router
# ============================================

api_router = APIRouter(prefix="/api")

@api_router.get("/pronostics/ui", response_class=HTMLResponse)
async def pronostics_ui(request: Request):
    """Serves the main HTML page for pronostics."""
    return templates.TemplateResponse("pronostics.html", {"request": request})

@api_router.get("/pronostics")
async def get_pronostics(date: str | None = Query(default=None, description="Date in YYYY-MM-DD format. Defaults to today (Paris time).")):

    date_to_use = date
    if date_to_use is None:
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        date_to_use = today.strftime("%Y-%m-%d")
    else:
        try:
            datetime.strptime(date_to_use, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date format. Please use YYYY-MM-DD.")

    correlation_id = str(uuid.uuid4())
    log_extra = {"correlation_id": correlation_id, "date": date_to_use}
    logger.info(f"Fetching pronostics for date: {date_to_use} from Firestore", extra=log_extra)
    logger.debug(f"DEBUG: get_pronostics for date: {date_to_use}", extra=log_extra)

    try:
        race_documents = firestore_client.get_races_by_date_prefix(date_to_use)
        logger.debug(f"DEBUG: Fetched {len(race_documents)} raw race documents for {date_to_use}", extra=log_extra)

        all_pronostics = []
        latest_update_time = None
        for doc in race_documents:
            analysis = doc.get("tickets_analysis")
            if analysis and analysis.get("tickets"):
                all_pronostics.append({
                    "rc": doc.get("rc", "N/A"),
                    "gpi_decision": analysis.get("gpi_decision", "N/A"),
                    "tickets": analysis.get("tickets", [])
                })

                # Track the latest update time
                last_analyzed_str = doc.get("last_analyzed_at")
                if last_analyzed_str:
                    try:
                        # Ensure timestamp is offset-aware for correct comparison
                        current_doc_time = datetime.fromisoformat(last_analyzed_str)
                        if latest_update_time is None or current_doc_time > latest_update_time:
                            latest_update_time = current_doc_time
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse last_analyzed_at: {last_analyzed_str}")

        final_last_updated = latest_update_time if latest_update_time else datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))

        return {
            "ok": True,
            "total_races": len(all_pronostics),
            "date": date_to_use,
            "last_updated": final_last_updated.isoformat().replace('+00:00', 'Z'),
            "pronostics": all_pronostics
        }
    except Exception:
        logger.error("Error fetching pronostics from Firestore", exc_info=True, extra=log_extra)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch pronostics from Firestore.")


@app.get("/ping")
async def ping():
    return {"status": "pong"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "hippique-orchestrator",
        "version": "2.1.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

@app.post("/schedule", status_code=status.HTTP_202_ACCEPTED)
async def schedule_daily_plan(body: ScheduleRequest):
    correlation_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "date": body.date, "mode": body.mode}
    logger.info("Schedule request received", extra=log_extra)

    try:
        plan = await build_plan_async(body.date)
        if not plan:
            logger.warning("Empty plan generated", extra=log_extra)
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"ok": False, "error": "No races found for this date"})

        logger.info(f"Plan built: {len(plan)} races", extra=log_extra)

        scheduled = schedule_all_races(plan=plan, mode=body.mode, correlation_id=correlation_id, trace_id=trace_id)

        success_h30 = sum(1 for s in scheduled if s["phase"] == "H30" and s["ok"])
        success_h5 = sum(1 for s in scheduled if s["phase"] == "H5" and s["ok"])
        all_ok = all(s["ok"] for s in scheduled)

        logger.info("Scheduling complete", extra={**log_extra, "success_h30": success_h30, "success_h5": success_h5})

        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={
            "ok": all_ok, "date": body.date, "total_races": len(plan),
            "scheduled_h30": success_h30, "scheduled_h5": success_h5,
            "mode": body.mode, "correlation_id": correlation_id, "trace_id": trace_id,
        })
    except Exception as e:
        logger.error(f"Schedule failed: {e}", exc_info=True, extra=log_extra)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"ok": False, "error": str(e)})


@app.post("/run")
async def run_race_analysis(body: RunRequest):
    correlation_id = str(uuid.uuid4())
    trace_id = body.trace_id or correlation_id
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "course_url": body.course_url, "phase": body.phase}
    logger.info("Run request received", extra=log_extra)

    try:
        result = run_course(course_url=body.course_url, phase=body.phase, date=body.date, correlation_id=correlation_id, trace_id=trace_id)
        result["correlation_id"] = correlation_id
        result["trace_id"] = trace_id

        status_code = status.HTTP_200_OK if result.get("ok") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=result)
    except Exception as e:
        logger.error(f"Run failed with exception: {e}", exc_info=True, extra=log_extra)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"ok": False, "error": str(e)})

# ============================================
# Task Endpoints (for Cloud Tasks)
# ============================================

@app.post("/tasks/bootstrap-day", status_code=status.HTTP_202_ACCEPTED)
async def tasks_bootstrap_day(body: ScheduleRequest, background_tasks: BackgroundTasks):
    correlation_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    logger.info("Bootstrap day task received", extra={"correlation_id": correlation_id, "trace_id": trace_id, "date": body.date})

    background_tasks.add_task(bootstrap_day_pipeline, date_str=body.date, correlation_id=correlation_id, trace_id=trace_id)

    return {"ok": True, "message": f"Bootstrap for {body.date} initiated in background."}

@app.post("/tasks/run-phase", status_code=status.HTTP_200_OK)
async def tasks_run_phase(body: RunRequest):
    correlation_id = str(uuid.uuid4())
    trace_id = body.trace_id or correlation_id
    logger.info(f"Run phase task received for course: {body.course_url}", extra={"correlation_id": correlation_id, "trace_id": trace_id})

    result = run_course(course_url=body.course_url, phase=body.phase, date=body.date, correlation_id=correlation_id, trace_id=trace_id)

    return {"ok": result.get("ok", False), "phase": result.get("phase"), "artifacts": result.get("artifacts", [])}

# ============================================
# API & Debug Endpoints
# ============================================

@app.get("/debug/parse")
async def debug_parse(date: str = "2025-10-17"):
    result = await build_plan_async(date)
    return {"ok": True, "date": date, "count": len(result), "races": result[:3] if result else []}

@app.get("/debug/config")
async def debug_config():
    """Returns the current application configuration."""
    config_dict = {k: str(v) for k, v in get_config().model_dump().items()}
    return {"ok": True, "config": config_dict}

@app.post("/debug/force-bootstrap/{date_str}", status_code=status.HTTP_202_ACCEPTED)
async def debug_force_bootstrap(date_str: str, background_tasks: BackgroundTasks):
    """
    Forces the daily bootstrap pipeline for a specific date, bypassing the "already planned" check.
    Useful for debugging and re-triggering planning.
    """
    correlation_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "date": date_str}
    logger.warning(f"Forcing bootstrap pipeline for {date_str} via debug endpoint.", extra=log_extra)

    # Clear the "day planned" status in Firestore if it exists, to ensure a fresh run
    # (Optional, but good for idempotence for debug endpoint)
    firestore_client.unmark_day_as_planned(date_str)

    background_tasks.add_task(bootstrap_day_pipeline, date_str=date_str, correlation_id=correlation_id, trace_id=trace_id)

    return {"ok": True, "message": f"Forced bootstrap for {date_str} initiated in background.", "correlation_id": correlation_id, "trace_id": trace_id}

@app.get("/debug/races/{race_doc_id}")
async def debug_get_race_document(race_doc_id: str):
    """
    Fetches a specific race document from the 'races' collection in Firestore.
    """
    correlation_id = str(uuid.uuid4())
    log_extra = {"correlation_id": correlation_id, "race_doc_id": race_doc_id}
    logger.info(f"Fetching race document: {race_doc_id} from Firestore via debug endpoint", extra=log_extra)

    try:
        doc = firestore_client.get_race_document("races", race_doc_id)
        if doc:
            return {"ok": True, "race_doc_id": race_doc_id, "data": doc}
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Race document {race_doc_id} not found.")
    except Exception:
        logger.error(f"Error fetching race document {race_doc_id} from Firestore", exc_info=True, extra=log_extra)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch race document from Firestore.")

# ============================================
# Core Logic (used by startup and endpoints)
# ============================================

async def bootstrap_day_pipeline(date_str: str, correlation_id: str, trace_id: str) -> dict[str, Any] | None:
    """Builds the plan for the day and schedules all races."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "date": date_str}
    logger.info(f"Starting bootstrap pipeline for {date_str}", extra=log_extra)
    plan = await build_plan_async(date_str)
    if not plan:
        logger.warning(f"No plan built for {date_str}. Aborting bootstrap.", extra=log_extra)
        return None

    logger.info(f"Plan built with {len(plan)} races. Now scheduling tasks.", extra=log_extra)
    logger.info(f"DEBUG_SERVICE: About to call schedule_all_races with {len(plan)} races.", extra=log_extra)
    print(f"DEBUG_PRINT_SERVICE: Plan before scheduling: {plan}")

    try:
        scheduled_tasks_results = schedule_all_races(plan=plan, mode="tasks", correlation_id=correlation_id, trace_id=trace_id)
    except Exception as e:
        logger.error(f"Failed to schedule all races: {e}", exc_info=True, extra=log_extra)
        scheduled_tasks_results = [] # Ensure it's still iterable for subsequent logic

    # Mark the day as planned ONLY if scheduling was successful for at least one race
    if plan and any(s["ok"] for s in scheduled_tasks_results):
        firestore_client.mark_day_as_planned(date_str, {
            "created_at": datetime.now(time_utils.get_tz()).isoformat(),
            "races_count": len(plan),
            "correlation_id": correlation_id
        })
        logger.info(f"Successfully marked {date_str} as planned in Firestore.", extra=log_extra)
    else:
        logger.warning(f"No races successfully scheduled for {date_str}. Not marking as planned.", extra=log_extra)

    return {"races_count": len(plan), "races": plan}

async def run_bootstrap_if_needed():
    """
    Checks if the daily planning has been done and runs it if not.
    This provides resilience against failed scheduler triggers.
    """
    await asyncio.sleep(10) # Wait a bit for other services to be ready if needed

    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    today_str = today.strftime("%Y-%m-%d")

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
            # Mark as planned is now handled inside bootstrap_day_pipeline
            logger.info(f"Successfully completed bootstrap for {today_str} on startup.", extra=log_extra)
    except Exception:
        logger.error(f"Startup bootstrap process for {today_str} failed.", exc_info=True, extra=log_extra)


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
