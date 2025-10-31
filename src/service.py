<<<<<<< HEAD
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

from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import get_config
from logging_utils import get_logger
from plan import build_plan_async
from runner import run_course
from scheduler import schedule_all_races

# ============================================
# Configuration
# ============================================

config = get_config()
logger = get_logger(__name__)

app = FastAPI(
    title="Hippique Orchestrator",
    description="Cloud Run service for automated horse racing analysis (GPI v5.1)",
    version="2.0.0",
)

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
    - /healthz
    - REQUIRE_AUTH=false
    """
    # Skip health check
    if request.url.path == "/healthz":
        return await call_next(request)
    
    # Skip if auth not required
    if not config.require_auth:
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

@app.get("/healthz")
async def health_check():
    """
    Health check endpoint.
    
    Returns 200 OK if service is running.
    """
    return {
        "status": "healthy",
        "service": "hippique-orchestrator",
        "version": "2.0.0",
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
          "correlation_id": "..."
        }
    """
    correlation_id = request.state.correlation_id
    
    logger.info(
        "Schedule request received",
        correlation_id=correlation_id,
        date=body.date,
        mode=body.mode,
    )
    
    try:
        # 1. Build plan asynchronously (parallel HTTP fetching)
        logger.info("Building daily plan...", correlation_id=correlation_id)
        plan = await build_plan_async(body.date)
        
        if not plan:
            logger.warning("Empty plan generated", correlation_id=correlation_id)
            return {
                "ok": False,
                "error": "No races found for this date",
                "date": body.date,
                "correlation_id": correlation_id,
            }
        
        logger.info(
            f"Plan built: {len(plan)} races",
            correlation_id=correlation_id,
            total_races=len(plan),
        )
        
        # 2. Schedule all races (H-30 + H-5)
        logger.info("Scheduling Cloud Tasks...", correlation_id=correlation_id)
        scheduled = schedule_all_races(
            plan=plan,
            mode=body.mode,
            correlation_id=correlation_id,
        )
        
        # 3. Build response
        success_h30 = sum(1 for s in scheduled if s["phase"] == "H30" and s["ok"])
        success_h5 = sum(1 for s in scheduled if s["phase"] == "H5" and s["ok"])
        
        logger.info(
            "Scheduling complete",
            correlation_id=correlation_id,
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
        
        return {
            "ok": True,
            "date": body.date,
            "total_races": len(plan),
            "scheduled_h30": success_h30,
            "scheduled_h5": success_h5,
            "mode": body.mode,
            "plan_summary": plan_summary,
            "scheduled_details": scheduled,
            "correlation_id": correlation_id,
        }
    
    except Exception as e:
        logger.error(
            f"Schedule failed: {e}",
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
    
    logger.info(
        "Run request received",
        correlation_id=correlation_id,
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
        )
        
        # Add correlation ID to result
        result["correlation_id"] = correlation_id
        
        # Log result
        if result.get("ok"):
            logger.info(
                "Run complete",
                correlation_id=correlation_id,
                phase=result.get("phase"),
                artifacts_count=len(result.get("artifacts", [])),
            )
        else:
            logger.error(
                "Run failed",
                correlation_id=correlation_id,
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

# ============================================
# Startup/Shutdown Events
# ============================================

@app.on_event("startup")
async def startup_event():
    """Log service startup"""
    logger.info(
        "Service starting",
        version="2.0.0",
        project_id=config.project_id,
        region=config.region,
        environment=config.environment,
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
=======
#!/usr/bin/env python3
"""Service FastAPI - Version Debug"""

import os
import sys
from pathlib import Path

# Forcer le PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, '/app')

print(f"[STARTUP] PYTHONPATH: {sys.path[:3]}", flush=True)
print(f"[STARTUP] CWD: {os.getcwd()}", flush=True)

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Literal
import uuid

# Config
try:
    from src.config import config
    print(f"[STARTUP] Config loaded: {config.project_id}", flush=True)
except Exception as e:
    print(f"[STARTUP] Config error: {e}", flush=True)
    config = None

try:
    from src.logging_utils import get_logger
    logger = get_logger(__name__)
    print("[STARTUP] Logger loaded", flush=True)
except Exception as e:
    print(f"[STARTUP] Logger error: {e}", flush=True)
    logger = None

# Create app FIRST
app = FastAPI(
    title="Hippique Orchestrator",
    version="2.0.0",
    description="Service d'orchestration hippique"
)

print(f"[STARTUP] FastAPI app created", flush=True)


# Models
class ScheduleRequest(BaseModel):
    date: str = "today"
    mode: Literal["tasks", "scheduler"] = "tasks"


class RunRequest(BaseModel):
    course_url: str
    phase: Literal["H-30", "H30", "H-5", "H5"]
    date: str


# Define ALL routes at module level (not inside functions)
@app.get("/")
def root():
    """Root endpoint."""
    return {"service": "hippique-orchestrator", "status": "running", "version": "2.0"}


@app.get("/healthz")
@app.get("/health")
def health():
    """Health check."""
    return {"status": "ok"}


@app.get("/ping")
def ping():
    """Simple ping."""
    return {"ping": "pong"}


@app.get("/debug/info")
def debug_info():
    """System info."""
    import sys
    return {
        "python": sys.version.split()[0],
        "cwd": os.getcwd(),
        "pythonpath": sys.path[:3],
        "project": getattr(config, 'project_id', 'unknown') if config else 'no-config',
    }


@app.get("/debug/parse")
async def debug_parse(date: str = "2025-10-17"):
    """Parse ZEturf."""
    correlation_id = str(uuid.uuid4())
    
    try:
        from src.plan import build_plan_async, ADVANCED_EXTRACTION
        result = await build_plan_async(date)
        
        return {
            "ok": True,
            "date": date,
            "count": len(result),
            "advanced_extraction": ADVANCED_EXTRACTION,
            "races": result[:3] if result else [],
            "correlation_id": correlation_id
        }
    except Exception as e:
        import traceback
        return {
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()[:500],
            "correlation_id": correlation_id
        }


@app.post("/schedule")
async def schedule(request: ScheduleRequest):
    """Schedule races."""
    correlation_id = str(uuid.uuid4())
    
    try:
        from src.plan import build_plan_async
        from datetime import datetime
        
        date_str = request.date if request.date != "today" else datetime.now().strftime("%Y-%m-%d")
        plan = await build_plan_async(date_str)
        
        if not plan:
            return {"ok": False, "error": "No races found", "correlation_id": correlation_id}
        
        # Programmer les tâches Cloud Tasks
        try:
            from src.scheduler import schedule_all_races
            
            # URL du service pour les callbacks
            service_url = "https://hippique-orchestrator-h3tdqmb7jq-ew.a.run.app"
            
            scheduled = schedule_all_races(
                plan=plan,
                mode=request.mode,
                run_url=f"{service_url}/run"
            )
            
            return {
                "ok": True,
                "date": date_str,
                "courses_count": len(plan),
                "tasks_created": scheduled.get("tasks_created", 0),
                "plan": plan[:5],
                "correlation_id": correlation_id
            }
        except Exception as sched_err:
            logger.error(f"Scheduling error: {sched_err}")
            return {
                "ok": True,
                "date": date_str,
                "courses_count": len(plan),
                "tasks_created": 0,
                "error": str(sched_err)[:200],
                "plan": plan[:5],
                "correlation_id": correlation_id
            }
        
    except Exception as e:
        import traceback
        return {
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()[:300],
            "correlation_id": correlation_id
        }


@app.post("/run")
async def run(request: RunRequest):
    """Run analysis."""
    return {
        "ok": False,
        "error": "Not implemented yet",
        "course_url": request.course_url,
        "phase": request.phase
    }


# Print routes on startup
print(f"[STARTUP] Registered {len(app.routes)} routes:", flush=True)
for route in app.routes:
    if hasattr(route, 'path') and hasattr(route, 'methods'):
        print(f"[STARTUP]   {list(route.methods)} {route.path}", flush=True)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    print(f"[STARTUP] Starting uvicorn on port {port}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

# Force rebuild marker: v2.1.0

# Build timestamp: 1760701009

# Force rebuild marker: v2.1.0

# Build timestamp: 1760701593
# Force final rebuild 1760710651
# Rebuild 1760711112
# Fix scheduler call 1760711520
# Fix scheduler call 1760717579
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
