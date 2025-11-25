"""
src/service.py - FastAPI Service Principal (VERSION DE DÉBOGAGE)
"""
from __future__ import annotations
import httpx
from fastapi import FastAPI, Request, status
from datetime import datetime
import uuid
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles # Added import
from pathlib import Path # Added import

# Réactivation du logger
from src.logging_utils import get_logger

from src.app_config import get_config

# Réactivation des modèles Pydantic
from pydantic import BaseModel, Field

# Réactivation des imports pour /schedule
import json
import traceback
from typing import Any, Dict, Optional
from fastapi import Response, HTTPException

from src.plan import build_plan_async
from src.scheduler import schedule_all_races
from src.api.tasks import router as tasks_router # Import the tasks router

# Réactivation de l'import pour /run
from src.runner import run_course

# Imports pour les endpoints de debug
import os
import sys


# ============================================
# Configuration
# ============================================

logger = get_logger(__name__)
config = get_config()

app = FastAPI(
    title="Hippique Orchestrator (Debug)",
    description="Debug version",
    version="debug",
)

# Définir le chemin absolu vers le répertoire statique
STATIC_DIR = Path(__file__).parent / "static"

app.include_router(tasks_router) # Include the tasks router

# Mount static files
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

# ============================================
# Middleware
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

# @app.middleware("http")
# async def verify_oidc_token(request: Request, call_next):
#     """
#     Verify OIDC token for authenticated endpoints.
    
#     Skips verification for:
#     - /healthz
#     - REQUIRE_AUTH=false
#     """
#     # Skip health check
#     if request.url.path == "/health":
#         return await call_next(request)
    
#     # Skip if auth not required
#     if not config.require_auth:
#         return await call_next(request)
    
#     # Verify Bearer token
#     auth_header = request.headers.get("Authorization", "")
#     if not auth_header.startswith("Bearer "):
#         logger.warning("Missing or invalid Authorization header")
#         return JSONResponse(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             content={"error": "Missing or invalid Authorization header"},
#         )
    
#     token = auth_header[7:]  # Remove "Bearer " prefix
    
#     # Basic validation (in production, verify signature against Google's JWKS)
#     if not token or len(token) < 10:
#         logger.warning("Invalid OIDC token")
#         return JSONResponse(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             content={"error": "Invalid OIDC token"},
#         )
    
#     # Token is valid, proceed
#     logger.debug("OIDC token validated")
#     return await call_next(request)

# ============================================
# Endpoints
# ============================================

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    """
    return {
        "status": "healthy",
        "service": "hippique-orchestrator (debug-version)",
        "version": "debug",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/health/scraping", status_code=status.HTTP_200_OK, summary="Check Scraping Service Health")
async def check_scraping_status(response: Response):
    """
    Checks if the scraping mechanism can successfully fetch data from the source.
    This is a dedicated health check for the scraping part of the application.
    """
    try:
        # This URL is based on the analysis of src/plan.py
        SOURCE_URL = "https://www.boturfers.fr/programme-pmu-du-jour"
        async with httpx.AsyncClient() as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            resp = await client.get(SOURCE_URL, headers=headers, timeout=10.0)
            resp.raise_for_status()
            if "<title>" not in resp.text:
                raise ValueError("Scraping check failed: page title not found.")
        return {"status": "ok", "message": "Scraping check successful."}
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "message": f"Scraping health check failed: {str(e)}"}

@app.get("/api/pronostics")
async def get_pronostics(request: Request, date: Optional[str] = None, analyses_base_dir: Path = Path("data/analyses")):
    """
    Endpoint to retrieve pronostics for a given date.
    """
    correlation_id = request.state.correlation_id
    
    if date is None or date == "today":
        target_date = datetime.now().strftime("%Y-%m-%d")
    else:
        target_date = date

    pronostics_data = []
    total_races = 0
    
    # Assuming analysis files are stored in a 'data/analyses' directory
    # and named like 'YYYY-MM-DD_R1C1_H5.json'
    analyses_dir = Path("data/analyses")
    
    if analyses_dir.exists() and analyses_dir.is_dir():
        for race_dir in analyses_dir.iterdir():
            if race_dir.is_dir():
                for analysis_file in race_dir.glob(f"{target_date}_*_H5.json"):
                    try:
                        with open(analysis_file, "r") as f:
                            data = json.load(f)
                            pronostics_data.append(data)
                            total_races += 1
                    except json.JSONDecodeError as e:
                        logger.error(f"Error decoding JSON from {analysis_file}: {e}", correlation_id=correlation_id)
                    except Exception as e:
                        logger.error(f"Error reading {analysis_file}: {e}", correlation_id=correlation_id)

    if not pronostics_data:
        return {
            "ok": False,
            "total_races": 0,
            "pronostics": [],
            "message": f"No pronostics found for {target_date}",
            "correlation_id": correlation_id,
        }
    
    return {
        "ok": True,
        "total_races": total_races,
        "pronostics": pronostics_data,
        "message": f"Successfully retrieved pronostics for {target_date}",
        "correlation_id": correlation_id,
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
        body.mode: "tasks" (default) or "scheduler" (Cloud Scheduler fallback)
    
    Returns:
        {
          "ok": True,
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
        
        all_tasks_ok = (success_h30 + success_h5) == len(scheduled)
        
        logger.info(
            "Scheduling complete",
            correlation_id=correlation_id,
            total=len(plan),
            success_h30=success_h30,
            success_h5=success_h5,
            all_tasks_ok=all_tasks_ok,
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
                "ok": all_tasks_ok,
                "date": body.date,
                "total_races": len(plan),
                "scheduled_h30": success_h30,
                "scheduled_h5": success_h5,
                "mode": body.mode,
                "plan_summary": plan_summary,
                "scheduled_details": scheduled,
                "correlation_id": correlation_id,
            },
        )
    
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
          "ok": True,
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
    )
    print(f"DEBUG: Type of config: {type(config)}")
    print(f"DEBUG: Attributes of config: {dir(config)}")

@app.on_event("shutdown")
async def shutdown_event():
    """Log service shutting down"""
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
        from src.plan import build_plan_async
        
        logger.info(f"Debug parse for {date}", extra={"correlation_id": correlation_id})
        result = await build_plan_async(date)
        
        return {
            "ok": True,
            "date": date,
            "count": len(result),
            "races": result[:3] if result else [],
            "correlation_id": correlation_id
        }
    except Exception as e:
        import traceback
        logger.error(f"Debug parse failed: {e}", extra={"correlation_id": correlation_id})
        return {
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "correlation_id": correlation_id
        }


@app.get("/debug/info")
async def debug_info():
    """Informations système"""
    import sys
    # from src.config import get_config # Removed this line
    # config = get_config() # Removed this line
    return {
        "python_version": sys.version,
        "cwd": os.getcwd(),
        "env": {
            "TZ": os.getenv("TZ"),
            "PROJECT_ID": config.project_id,
            "REGION": config.region,
        }
    }