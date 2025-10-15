"""
Service principal Cloud Run pour orchestration analyse hippique GPI v5.1
Endpoints: POST /schedule, POST /run, GET /healthz
"""
import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
import google.auth
from google.auth.transport import requests as google_requests

from src.config import Config
from src.logging_utils import setup_logging, get_correlation_id
from src.plan import build_plan
from src.scheduler import CloudTasksScheduler, CloudSchedulerFallback
from src.runner import CourseRunner

# Setup logging
logger = setup_logging()
config = Config()

# OIDC verification
def verify_oidc_token(request: Request) -> Optional[Dict[str, Any]]:
    """Vérifie le token OIDC si REQUIRE_AUTH=true"""
    if not config.REQUIRE_AUTH:
        return {"sub": "anonymous"}
    
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = auth_header.split(" ")[1]
    try:
        request_adapter = google_requests.Request()
        id_info = google.oauth2.id_token.verify_oauth2_token(
            token, request_adapter, audience=config.SERVICE_URL
        )
        return id_info
    except Exception as e:
        logger.error(f"OIDC verification failed: {e}")
        raise HTTPException(status_code=403, detail="Invalid token")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management"""
    logger.info("Starting service", extra={
        "project_id": config.PROJECT_ID,
        "region": config.REGION,
        "service": config.SERVICE_NAME
    })
    yield
    logger.info("Shutting down service")

app = FastAPI(
    title="Analyse Hippique Orchestrator",
    version="1.0.0",
    lifespan=lifespan
)

# Request Models
class ScheduleRequest(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD or 'today'")
    mode: str = Field(default="tasks", description="tasks|scheduler")
    
    @validator('date')
    def validate_date(cls, v):
        if v == "today":
            from src.time_utils import now_paris
            return now_paris().strftime("%Y-%m-%d")
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError("Date must be YYYY-MM-DD or 'today'")
    
    @validator('mode')
    def validate_mode(cls, v):
        if v not in ["tasks", "scheduler"]:
            raise ValueError("Mode must be 'tasks' or 'scheduler'")
        return v

class RunRequest(BaseModel):
    course_url: str = Field(..., description="URL course ZEturf")
    phase: str = Field(..., description="H-30|H30|H-5|H5")
    date: str = Field(..., description="YYYY-MM-DD")
    
    @validator('phase')
    def normalize_phase(cls, v):
        v_upper = v.upper().replace("-", "")
        if v_upper not in ["H30", "H5"]:
            raise ValueError("Phase must be H-30, H30, H-5, or H5")
        return v_upper

# Endpoints
@app.get("/healthz")
async def healthz():
    """Health check"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.post("/schedule")
async def schedule(
    req: ScheduleRequest,
    request: Request,
    user: Dict = Depends(verify_oidc_token)
):
    """
    Génère le plan du jour et programme les tâches H-30/H-5
    """
    correlation_id = get_correlation_id()
    logger.info("Schedule request received", extra={
        "correlation_id": correlation_id,
        "date": req.date,
        "mode": req.mode,
        "user": user.get("sub", "unknown")
    })
    
    try:
        # Build plan
        logger.info(f"Building plan for {req.date}")
        plan = build_plan(req.date)
        
        if not plan:
            logger.warning(f"No races found for {req.date}")
            return JSONResponse({
                "ok": True,
                "date": req.date,
                "races_count": 0,
                "message": "No races found for this date",
                "scheduled_tasks": []
            })
        
        # Save plan.json
        from pathlib import Path
        plan_file = Path(config.DATA_DIR) / f"plan_{req.date}.json"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        with open(plan_file, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        logger.info(f"Plan saved to {plan_file}, {len(plan)} races")
        
        # Upload to GCS if configured
        if config.GCS_BUCKET:
            from google.cloud import storage
            client = storage.Client(project=config.PROJECT_ID)
            bucket = client.bucket(config.GCS_BUCKET)
            blob_name = f"{config.GCS_PREFIX}/plans/plan_{req.date}.json"
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(plan_file))
            logger.info(f"Plan uploaded to gs://{config.GCS_BUCKET}/{blob_name}")
        
        # Schedule tasks
        scheduled = []
        if req.mode == "tasks":
            scheduler = CloudTasksScheduler(config)
        else:
            scheduler = CloudSchedulerFallback(config)
        
        run_url = f"{config.SERVICE_URL}/run"
        
        from src.time_utils import parse_time_local, subtract_minutes
        
        for race in plan:
            race_id = f"{race['r_label']}{race['c_label']}"
            
            # Parse race time (HH:MM in Europe/Paris)
            race_time_str = race.get('time_local')
            if not race_time_str:
                logger.warning(f"No time for {race_id}, skipping")
                continue
            
            try:
                race_dt = parse_time_local(req.date, race_time_str)
            except Exception as e:
                logger.error(f"Failed to parse time for {race_id}: {e}")
                continue
            
            # Schedule H-30 and H-5
            h30_dt = subtract_minutes(race_dt, 30)
            h5_dt = subtract_minutes(race_dt, 5)
            
            payload_h30 = {
                "course_url": race['course_url'],
                "phase": "H30",
                "date": req.date
            }
            payload_h5 = {
                "course_url": race['course_url'],
                "phase": "H5",
                "date": req.date
            }
            
            try:
                task_h30 = scheduler.schedule_task(
                    run_url=run_url,
                    race_id=race_id,
                    phase="h30",
                    when_local=h30_dt,
                    payload=payload_h30,
                    date=req.date
                )
                task_h5 = scheduler.schedule_task(
                    run_url=run_url,
                    race_id=race_id,
                    phase="h5",
                    when_local=h5_dt,
                    payload=payload_h5,
                    date=req.date
                )
                
                scheduled.append({
                    "race_id": race_id,
                    "race_time": race_time_str,
                    "h30_scheduled": h30_dt.isoformat(),
                    "h5_scheduled": h5_dt.isoformat(),
                    "tasks": [task_h30, task_h5]
                })
                
            except Exception as e:
                logger.error(f"Failed to schedule {race_id}: {e}", exc_info=True)
                scheduled.append({
                    "race_id": race_id,
                    "error": str(e)
                })
        
        response = {
            "ok": True,
            "correlation_id": correlation_id,
            "date": req.date,
            "races_count": len(plan),
            "scheduled_count": len([s for s in scheduled if "error" not in s]),
            "mode": req.mode,
            "scheduled_tasks": scheduled
        }
        
        logger.info("Schedule completed", extra={
            "correlation_id": correlation_id,
            "races": len(plan),
            "scheduled": response["scheduled_count"]
        })
        
        return JSONResponse(response)
        
    except Exception as e:
        logger.error(f"Schedule failed: {e}", exc_info=True, extra={
            "correlation_id": correlation_id
        })
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/run")
async def run(
    req: RunRequest,
    request: Request,
    user: Dict = Depends(verify_oidc_token)
):
    """
    Exécute l'analyse d'une course (H-30 ou H-5)
    """
    correlation_id = get_correlation_id()
    logger.info("Run request received", extra={
        "correlation_id": correlation_id,
        "course_url": req.course_url,
        "phase": req.phase,
        "date": req.date,
        "user": user.get("sub", "unknown")
    })
    
    try:
        runner = CourseRunner(config)
        result = runner.run_course(
            course_url=req.course_url,
            phase=req.phase,
            date=req.date,
            correlation_id=correlation_id
        )
        
        logger.info("Run completed", extra={
            "correlation_id": correlation_id,
            "success": result["ok"],
            "rc": result.get("rc")
        })
        
        return JSONResponse(result)
        
    except Exception as e:
        logger.error(f"Run failed: {e}", exc_info=True, extra={
            "correlation_id": correlation_id
        })
        raise HTTPException(status_code=500, detail=str(e))
