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