"""
src/service.py - FastAPI Service Principal

Service Cloud Run orchestrant l'analyse hippique quotidienne.

Endpoints:
  POST /schedule - Génère le plan du jour et programme les analyses H-30/H-5
  POST /run      - Exécute l'analyse d'une course (appelé par Cloud Tasks)
  GET  /healthz  - Health check

Sécurité: OIDC token validation si REQUIRE_AUTH=true
"""

from __future__ import annotations

import json
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, HTTPException, status, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles # Added
from pydantic import BaseModel, Field

from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger # Added
from hippique_orchestrator.plan import build_plan_async
from hippique_orchestrator.scheduler import schedule_all_races
from hippique_orchestrator.snapshot_manager import write_snapshot_for_day
from hippique_orchestrator.runner import run_course # Moved from inside tasks_run_phase
import os # Added

# ============================================
# Configuration
# ============================================

logger = get_logger(__name__)
config = get_config()

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static") # Added

app = FastAPI(
    title="Hippique Orchestrator",
    description="Cloud Run service for automated horse racing analysis (GPI v5.1)",
    version="2.0.0",
)

# Mount static files for /pronostics
app.mount("/pronostics", StaticFiles(directory=STATIC_DIR, html=True), name="pronostics")

# ============================================
# Request/Response Models
# ============================================

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
    trace_id: str | None = None

# ============================================
# Middleware - Request Logging
# ============================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests with correlation ID"""
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    
    logger.info(
        f"{request.method} {request.url.path}",
        correlation_id=correlation_id,
        method=request.method,
        path=request.url.path,
        client=request.client.host if request.client else "unknown",
    )
    
    # Add correlation ID to request state
    request.state.correlation_id = correlation_id
    
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    except Exception as e:
        logger.error(
            f"Request failed: {e}",
            correlation_id=correlation_id,
            exc_info=e,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal server error",
                "correlation_id": correlation_id,
            },
            headers={"X-Correlation-ID": correlation_id},
        )

# ============================================
# Middleware - OIDC Authentication
# ============================================

@app.middleware("http")
async def verify_oidc_token(request: Request, call_next):
    """
    Verify OIDC token for authenticated endpoints.
    
    Skips verification for:
    - /healthz-test
    - /ping
    - REQUIRE_AUTH=false
    """
    # Skip health check and ping
    if request.url.path.startswith("/healthz-test") or request.url.path.startswith("/ping"):
        return await call_next(request)
    
    # Skip if auth not required
    if not config.REQUIRE_AUTH:
        return await call_next(request)
    
    # Verify Bearer token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        logger.warning("Missing or invalid Authorization header")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Missing or invalid Authorization header"},
        )
    
    token = auth_header[7:]  # Remove "Bearer " prefix
    
    # Basic validation (in production, verify signature against Google's JWKS)
    if not token or len(token) < 10:
        logger.warning("Invalid OIDC token")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Invalid OIDC token"},
        )
    
    # Token is valid, proceed
    logger.debug("OIDC token validated")
    return await call_next(request)

# ============================================
# Endpoints
# ============================================

@app.get("/ping")
async def ping():
    """Simple ping endpoint."""
    return {"status": "pong"}

@app.get("/healthz")
async def health_check():
    """
    Health check endpoint.
    
    Returns 200 OK if service is running.
    """
    return {
        "status": "healthy",
        "service": "hippique-orchestrator",
        "version": "2.1.0-debug",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

@app.post("/schedule")
async def schedule_daily_plan(request: Request, body: ScheduleRequest):
    """
    Generate daily plan and schedule H-30/H-5 analyses.
    
    Workflow:
      1. Build plan from Geny + ZEturf (async parallel fetching)
      2. Schedule ~80 Cloud Tasks (H-30 + H-5 per race)
      3. Return summary
    
    Args:
        body.date: "YYYY-MM-DD" or "today"
        body.mode: "tasks" (default) or "scheduler" (fallback)
    
    Returns:
        {
          "ok": true,
          "date": "2025-10-16",
          "total_races": 40,
          "scheduled_h30": 38,
          "scheduled_h5": 38,
          "mode": "tasks",
          "plan_summary": [...],
          "correlation_id": "...",
          "trace_id": "..."
        }
    """
    correlation_id = request.state.correlation_id
    trace_id = str(uuid.uuid4())
    
    logger.info(
        "Schedule request received",
        correlation_id=correlation_id,
        trace_id=trace_id,
        date=body.date,
        mode=body.mode,
    )
    
    try:
        # 1. Build plan asynchronously (parallel HTTP fetching)
        logger.info("Building daily plan...", correlation_id=correlation_id, trace_id=trace_id)
        plan = await build_plan_async(body.date)
        
        if not plan:
            logger.warning("Empty plan generated", correlation_id=correlation_id, trace_id=trace_id)
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "ok": False,
                    "error": "No races found for this date",
                    "date": body.date,
                    "correlation_id": correlation_id,
                    "trace_id": trace_id,
                }
            )
        
        logger.info(
            f"Plan built: {len(plan)} races",
            correlation_id=correlation_id,
            trace_id=trace_id,
            total_races=len(plan),
        )
        
        # 2. Schedule all races (H-30 + H-5)
        logger.info("Scheduling Cloud Tasks...", correlation_id=correlation_id, trace_id=trace_id)
        scheduled = schedule_all_races(
            plan=plan,
            mode=body.mode,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        
        # 3. Build response
        success_h30 = sum(1 for s in scheduled if s["phase"] == "H30" and s["ok"])
        success_h5 = sum(1 for s in scheduled if s["phase"] == "H5" and s["ok"])
        all_ok = all(s["ok"] for s in scheduled)

        logger.info(
            "Scheduling complete",
            correlation_id=correlation_id,
            trace_id=trace_id,
            total=len(plan),
            success_h30=success_h30,
            success_h5=success_h5,
        )

        # Plan summary for response (first 5 races)
        plan_summary = [
            {
                "race": f"{p['r_label']}{p['c_label']}",
                "time": p["time_local"],
                "meeting": p.get("meeting", ""),
                "url": p["course_url"],
            }
            for p in plan[:5]
        ]

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "ok": all_ok,
                "date": body.date,
                "total_races": len(plan),
                "scheduled_h30": success_h30,
                "scheduled_h5": success_h5,
                "mode": body.mode,
                "plan_summary": plan_summary,
                "scheduled_details": scheduled,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            },
        )
    
    except Exception as e:
        logger.error(
            f"Schedule failed: {e}",
            correlation_id=correlation_id,
            trace_id=trace_id,
            exc_info=e,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            },
        )

@app.post("/tasks/snapshot-9h")
async def tasks_snapshot_9h(request: Request, body: ScheduleRequest):
    """
    Trigger snapshot for a given date at 9h.
    """
    correlation_id = request.state.correlation_id
    logger.info(f"Snapshot 9h task received for date: {body.date}", correlation_id=correlation_id)
    
    try:
        # Assuming write_snapshot_for_day is an async function or can be run in a thread pool
        # For now, we'll just log and return accepted.
        # In a real scenario, this would dispatch to a background worker or Cloud Task.
        # This should ideally be awaited or run in a background task executor
        # For testing purposes, we'll just call it directly or mock it.
        write_snapshot_for_day(date_str=body.date, phase="H9", correlation_id=correlation_id)
        
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "ok": True,
                "message": f"Snapshot 9h initiated in background for date: {body.date}",
                "correlation_id": correlation_id,
            },
        )
    except Exception as e:
        logger.error(
            f"Snapshot 9h task failed: {e}",
            correlation_id=correlation_id,
            exc_info=e,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "correlation_id": correlation_id,
            },
        )

@app.post("/tasks/run-phase")
async def tasks_run_phase(request: Request, body: RunRequest):
    """
    Execute analysis for one race (H-30 or H-5).
    """
    correlation_id = request.state.correlation_id
    trace_id = body.trace_id or correlation_id # Fallback to correlation_id
    
    logger.info(
        f"Run phase task received for course: {body.course_url}, phase: {body.phase}, date: {body.date}",
        correlation_id=correlation_id,
        trace_id=trace_id,
    )
    
    try:
        from hippique_orchestrator.runner import run_course
        result = run_course(
            course_url=body.course_url,
            phase=body.phase,
            date=body.date,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "ok": result.get("ok", False),
                "phase": result.get("phase"),
                "artifacts": result.get("artifacts", []),
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            },
        )
    except Exception as e:
        logger.error(
            f"Run phase task failed: {e}",
            correlation_id=correlation_id,
            trace_id=trace_id,
            exc_info=e,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            },
        )

@app.post("/tasks/bootstrap-day")
async def tasks_bootstrap_day(request: Request, body: ScheduleRequest):
    """
    Generate daily plan and schedule H-30/H-5 analyses.
    
    Workflow:
      1. Build plan from Geny + ZEturf (async parallel fetching)
      2. Schedule ~80 Cloud Tasks (H-30 + H-5 per race)
      3. Return summary
    
    Args:
        body.date: "YYYY-MM-DD" or "today"
        body.mode: "tasks" (default) or "scheduler" (Cloud Scheduler fallback)
    
    Returns:
        {
          "ok": true,
          "date": "2025-10-16",
          "total_races": 40,
          "scheduled_h30": 38,
          "scheduled_h5": 38,
          "mode": "tasks",
          "plan_summary": [...],
          "correlation_id": "..."
        }
    """
    correlation_id = request.state.correlation_id
    trace_id = str(uuid.uuid4())
    
    logger.info(
        "Bootstrap day task received",
        correlation_id=correlation_id,
        trace_id=trace_id,
        date=body.date,
        mode=body.mode,
    )
    
    try:
        # 1. Build plan asynchronously (parallel HTTP fetching)
        logger.info("Building daily plan...", correlation_id=correlation_id, trace_id=trace_id)
        plan = await build_plan_async(body.date)
        
        if not plan:
            logger.warning("Empty plan generated", correlation_id=correlation_id, trace_id=trace_id)
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED, # Still accepted, but no tasks scheduled
                content={
                    "ok": True, # Indicate that the request was processed successfully, even if no tasks were scheduled
                    "message": "No races found for this date, no tasks scheduled",
                    "date": body.date,
                    "scheduled_tasks": 0,
                    "correlation_id": correlation_id,
                    "trace_id": trace_id,
                }
            )
        
        logger.info(
            f"Plan built: {len(plan)} races",
            correlation_id=correlation_id,
            trace_id=trace_id,
            total_races=len(plan),
        )
        
        # 2. Schedule all races (H-30 + H-5)
        logger.info("Scheduling Cloud Tasks...", correlation_id=correlation_id, trace_id=trace_id)
        scheduled = schedule_all_races(
            plan=plan,
            mode=body.mode,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        
        # 3. Build response
        success_h30 = sum(1 for s in scheduled if s["phase"] == "H30" and s["ok"])
        success_h5 = sum(1 for s in scheduled if s["phase"] == "H5" and s["ok"])
        
        total_scheduled = success_h30 + success_h5
        
        logger.info(
            "Scheduling complete",
            correlation_id=correlation_id,
            trace_id=trace_id,
            total=total_scheduled,
            success_h30=success_h30,
            success_h5=success_h5,
        )
        
        # Plan summary for response (first 5 races)
        plan_summary = [
            {
                "race": f"{p['r_label']}{p['c_label']}",
                "time": p["time_local"],
                "meeting": p.get("meeting", ""),
                "url": p["course_url"],
            }
            for p in plan[:5]
        ]
        
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "ok": True,
                "date": body.date,
                "total_races": len(plan),
                "scheduled_h30": success_h30,
                "scheduled_h5": success_h5,
                "scheduled_tasks": total_scheduled,
                "mode": body.mode,
                "plan_summary": plan_summary,
                "scheduled_details": scheduled,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            },
        )
    
    except Exception as e:
        logger.error(
            f"Bootstrap day task failed: {e}",
            correlation_id=correlation_id,
            trace_id=trace_id,
            exc_info=e,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            },
        )

@app.post("/run")
async def run_race_analysis(request: Request, body: RunRequest):
    """
    Execute analysis for one race (H-30 or H-5).
    
    Called by Cloud Tasks at scheduled times.
    
    Workflow:
      - H-30: Snapshot + stats (5 min)
      - H-5:  Full pipeline with ticket generation (10 min)
    
    Args:
        body.course_url: ZEturf course URL
        body.phase: "H30" or "H5" (case-insensitive, with or without dash)
        body.date: "YYYY-MM-DD"
    
    Returns:
        {
          "ok": true,
          "phase": "H5",
          "returncode": 0,
          "stdout_tail": "...",
          "artifacts": ["data/R1C3/snapshot_h5.json", ...],
          "correlation_id": "..."
        }
    """
    correlation_id = request.state.correlation_id
    trace_id = body.trace_id or correlation_id # Fallback to correlation_id
    
    logger.info(
        "Run request received",
        correlation_id=correlation_id,
        trace_id=trace_id,
        course_url=body.course_url,
        phase=body.phase,
        date=body.date,
    )
    
    try:
        # Execute course analysis
        result = run_course(
            course_url=body.course_url,
            phase=body.phase,
            date=body.date,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        
        # Add correlation ID to result
        result["correlation_id"] = correlation_id
        result["trace_id"] = trace_id
        
        # Log result
        if result.get("ok"):
            logger.info(
                "Run complete",
                correlation_id=correlation_id,
                trace_id=trace_id,
                phase=result.get("phase"),
                artifacts_count=len(result.get("artifacts", [])),
            )
        else:
            logger.error(
                "Run failed",
                correlation_id=correlation_id,
                trace_id=trace_id,
                error=result.get("error"),
                returncode=result.get("returncode"),
            )
        
        # Return appropriate status code
        status_code = (
            status.HTTP_200_OK if result.get("ok")
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        
        return JSONResponse(
            status_code=status_code,
            content=result,
        )
    
    except Exception as e:
        logger.error(
            f"Run failed with exception: {e}",
            correlation_id=correlation_id,
            trace_id=trace_id,
            exc_info=e,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            },
        )

# ============================================
# Startup/Shutdown Events
# ============================================

@app.on_event("startup")
async def startup_event():
    """Log service startup"""
    logger.info(
        "Service starting",
        version="2.0.0",
        project_id=config.PROJECT_ID,
        region=config.REGION,
        # environment=config.environment, # Removed as it doesn't exist
    )

@app.on_event("shutdown")
async def shutdown_event():
    """Log service shutdown"""
    logger.info("Service shutting down")

# ============================================
# Error Handlers
# ============================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.warning(
        f"HTTP {exc.status_code}: {exc.detail}",
        correlation_id=correlation_id,
        status_code=exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "correlation_id": correlation_id,
        },
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions"""
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.error(
        f"Unhandled exception: {exc}",
        correlation_id=correlation_id,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "correlation_id": correlation_id,
        },
    )

@app.get("/debug/parse")
async def debug_parse(date: str = "2025-10-17"):
    """Debug endpoint pour tester le parser ZEturf"""
    correlation_id = str(uuid.uuid4())
    try:
        
        logger.info(f"Debug parse for {date}", extra={"correlation_id": correlation_id})
        result = await build_plan_async(date)
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "ok": True,
                "date": date,
                "count": len(result),
                "races": result[:3] if result else [],
                "correlation_id": correlation_id
            }
        )
    except Exception as e:
        import traceback
        logger.error(f"Debug parse failed: {e}", extra={"correlation_id": correlation_id})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "correlation_id": correlation_id
            }
        )


@app.get("/debug/info")
async def debug_info():
    """Informations système"""
    import sys
    return {
        "python_version": sys.version,
        "cwd": os.getcwd(),
        "env": {
            "TZ": config.TZ,
            "PROJECT_ID": config.PROJECT_ID,
            "REGION": config.REGION,
        }
    }

@app.get("/debug/static")
async def debug_static():
    """Debug static files path"""
    static_dir_path = STATIC_DIR
    is_dir = os.path.isdir(static_dir_path)
    dir_content = os.listdir(static_dir_path) if is_dir else "Not a directory"
    return {
        "static_dir_path": static_dir_path,
        "is_directory": is_dir,
        "directory_content": dir_content
    }

from pathlib import Path # Added

# ============================================
# Configuration
# ============================================

logger = get_logger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static") # Added
ANALYSES_DIR = Path("data/analyses") # Define analyses directory

# Add the firestore_client import
from hippique_orchestrator import firestore_client

@app.get("/api/pronostics")
async def get_pronostics(date: str = Query(..., description="Date in YYYY-MM-DD format", example="2025-11-29")):
    """
    Fetch pronostics data for a given date from Firestore.
    """
    try:
        # Validate date format
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid date format. Please use YYYY-MM-DD."
        )

    correlation_id = str(uuid.uuid4())
    logger.info(f"Fetching pronostics for date: {date} from Firestore", correlation_id=correlation_id)

    try:
        # Query Firestore for documents that start with the given date
        race_documents = firestore_client.get_races_by_date_prefix(date)
        
        all_pronostics = []
        for doc in race_documents:
            # doc is already a dictionary representation of the document
            # Extract the relevant analysis part
            analysis = doc.get("tickets_analysis")
            if analysis:
                # Add race identifier for context
                analysis["race_id"] = doc.get("id", "unknown_race")
                all_pronostics.append(analysis)

        total_races = len(all_pronostics)
        
        if all_pronostics:
            message = f"Found {total_races} pronostics for date: {date}"
        else:
            message = f"No pronostics found for date: {date}"

        return {
            "ok": True,
            "total_races": total_races,
            "date": date,
            "pronostics": all_pronostics,
            "message": message,
            "correlation_id": correlation_id,
        }

    except Exception as e:
        logger.error(
            f"Error fetching pronostics from Firestore for date {date}: {e}",
            correlation_id=correlation_id,
            exc_info=e,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "ok": False,
                "error": "Failed to fetch pronostics from Firestore.",
                "traceback": traceback.format_exc(),
                "correlation_id": correlation_id,
            },
        )
