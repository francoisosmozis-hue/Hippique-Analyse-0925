from __future__ import annotations

import hashlib
import json
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Request, Response, Security
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__, analysis_pipeline, config, firestore_client, plan, scheduler
from .api import tasks # Import the tasks router
from .auth import check_api_key, verify_oidc_token
from .logging_middleware import logging_middleware
from .logging_utils import (
    setup_logging,
)
from .schemas import ScheduleRequest, ScheduleResponse

# --- Configuration & Initialization ---
setup_logging(log_level=config.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting Hippique Orchestrator v{__version__}")
    yield
    logger.info("Shutting down Hippique Orchestrator.")


BASE_DIR = Path(__file__).resolve().parent.parent
app = FastAPI(title="Hippique Orchestrator", version=__version__, lifespan=lifespan, redoc_url=None)

# --- Include Routers ---
app.include_router(tasks.router) # Include the tasks router

# --- Middlewares ---
app.add_middleware(BaseHTTPMiddleware, dispatch=logging_middleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# --- UI Endpoints ---
@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/pronostics")


@app.get("/pronostics", response_class=HTMLResponse, tags=["UI"])
@app.get("/pronostics/", response_class=HTMLResponse, tags=["UI"])
async def get_pronostics_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/pronostics/ui", include_in_schema=False)
async def redirect_legacy_ui():
    """Redirects old UI path to the new one."""
    return RedirectResponse(url="/pronostics", status_code=307)


@app.get("/api/pronostics/ui", include_in_schema=False)
async def redirect_legacy_api_ui():
    """Redirects old API UI path to the new one."""
    return RedirectResponse(url="/api/pronostics", status_code=307)


# --- API Endpoints ---
@app.get("/api/pronostics", tags=["API"])
async def get_pronostics_data(date: str | None = None, if_none_match: str | None = Header(None)):
    """
    Main endpoint to get daily pronostics.
    Combines data from the daily plan and Firestore.
    """
    try:
        date_str = date or datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")
        datetime.strptime(date_str, "%Y-%m-%d")  # Validate format
    except ValueError as e:
        raise HTTPException(
            status_code=422, detail="Invalid date format. Please use YYYY-MM-DD."
        ) from e

    server_timestamp = datetime.now(timezone.utc)
    races_from_db = firestore_client.get_races_for_date(date_str)
    daily_plan = await plan.build_plan_async(date_str)

    all_races_map = {}
    for race in daily_plan:
        r_label = race.get("r_label")
        c_label = race.get("c_label")
        if r_label and c_label:
            rc_key = f"{r_label}{c_label}"
            all_races_map[rc_key] = race

    counts = {
        "total_in_plan": len(daily_plan),
        "total_processed": len(races_from_db),
        "total_analyzed": 0,
        "total_playable": 0,
        "total_abstain": 0,
        "total_error": 0,
    }

    pronostics = []
    last_updated_from_db = None
    processed_races_rc = set()

    for race_doc in races_from_db:
        race_data = race_doc.to_dict()
        processed_races_rc.add(race_doc.id.split('_')[-1])

        analysis = race_data.get("tickets_analysis", {})
        decision = analysis.get("gpi_decision", "Pending").lower()

        if "play" in decision:
            race_data["status"] = "playable"
            counts["total_playable"] += 1
        elif "abstain" in decision:
            race_data["status"] = "abstain"
            counts["total_abstain"] += 1
        elif "error" in decision:
            race_data["status"] = "error"
            counts["total_error"] += 1
        else:
            race_data["status"] = "pending"

        if "tickets_analysis" in race_data:
            counts["total_analyzed"] += 1

        pronostics.append(race_data)

        if updated_at_str := race_data.get("last_analyzed_at"):
            updated_at = datetime.fromisoformat(updated_at_str)
            if last_updated_from_db is None or updated_at > last_updated_from_db:
                last_updated_from_db = updated_at

    for rc_label, plan_race in all_races_map.items():
        if rc_label not in processed_races_rc:
            pronostics.append(
                {
                    "rc": rc_label,
                    "nom": plan_race.get("name"),
                    "num": plan_race.get("c_label"),
                    "reunion": plan_race.get("r_label"),
                    "heure_depart": plan_race.get("time_local"),
                    "status": "pending",
                    "gpi_decision": None,
                    "tickets_analysis": None,
                }
            )

    counts["total_pending"] = counts["total_in_plan"] - counts["total_processed"]

    status_message = (
        f"{counts['total_processed']}/{counts['total_in_plan']} courses traitées. "
        f"Jouables: {counts['total_playable']}, Abstention: {counts['total_abstain']}, "
        f"Erreurs: {counts['total_error']}, En attente: {counts['total_pending']}."
    )

    source = "empty"
    reason_if_empty = None
    if pronostics:
        source = "firestore" if races_from_db else "plan_fallback"
    else:
        reason_if_empty = "No races found in daily plan or Firestore for this date."

    response_content = {
        "ok": True,
        "date": date_str,
        "source": source,
        "reason_if_empty": reason_if_empty,
        "status_message": status_message,
        "last_updated": (last_updated_from_db or server_timestamp).isoformat(),
        "version": __version__,
        "counts": counts,
        "pronostics": pronostics,
    }

    content_hash = hashlib.sha1(json.dumps(response_content, sort_keys=True).encode()).hexdigest()
    etag = f'"{content_hash}"'
    if if_none_match == etag:
        return Response(status_code=304)

    return JSONResponse(content=response_content, headers={"ETag": etag})


@app.post("/schedule", tags=["Orchestration"], response_model=ScheduleResponse)
async def schedule_day_races(
    request: Request, schedule_request: ScheduleRequest, api_key: str = Security(check_api_key)
):
    logger.info(
        "Received request to schedule day races. Force: %s, Dry Run: %s",
        schedule_request.force,
        schedule_request.dry_run,
    )
    try:
        date_str = schedule_request.date or datetime.now(ZoneInfo(config.TIMEZONE)).strftime(
            "%Y-%m-%d"
        )
        datetime.strptime(date_str, "%Y-%m-%d")  # Validate format

        plan_date = date_str
        daily_plan = await plan.build_plan_async(plan_date)

        if not daily_plan:
            msg = f"No races found in plan for {plan_date}. Nothing to schedule."
            logger.warning(msg)
            return ScheduleResponse(message=msg, races_in_plan=0, details=[])

        # Deduce service URL from the incoming request
        service_url = f"https://{request.url.netloc}"
        logger.info(
            "Built plan with %d races. Passing to scheduler with service_url: %s",
            len(daily_plan),
            service_url,
        )

        schedule_results = scheduler.schedule_all_races(
            plan=daily_plan,
            service_url=service_url,
            force=schedule_request.force,
            dry_run=schedule_request.dry_run,
        )

        return ScheduleResponse(
            message=f"Scheduling process complete for {date_str}.",
            races_in_plan=len(daily_plan),
            details=schedule_results,
        )

    except ValueError as e:
        logger.warning(f"Invalid date format provided: {e}")
        raise HTTPException(status_code=422, detail=f"Invalid date format: {e}") from e
    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(f"UNHANDLED EXCEPTION in /schedule endpoint: {e}\nTRACEBACK:\n{tb_str}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}") from e


@app.get("/ops/status", tags=["Operations"])
async def get_ops_status(date: str | None = None, api_key: str = Security(check_api_key)):
    try:
        date_str = date or datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")
        datetime.strptime(date_str, "%Y-%m-%d")  # Validate format
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.") from e

    daily_plan = await plan.build_plan_async(date_str)
    return firestore_client.get_processing_status_for_date(date_str, daily_plan)


@app.post("/ops/run", tags=["Operations"])
async def run_single_race(rc: str, api_key: str = Security(check_api_key)):
    """Manually triggers the analysis pipeline for a single race."""
    date_str = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")
    logger.info(f"Manual run triggered for race {rc} on {date_str}")

    daily_plan = await plan.build_plan_async(date_str)
    target_race = next((r for r in daily_plan if f"{r.get('r_label')}{r.get('c_label')}" == rc), None)

    if not target_race:
        raise HTTPException(status_code=404, detail=f"Race {rc} not found in plan for {date_str}")

    doc_id = f"{date_str}_{rc}"
    course_url = target_race.get("url")
    if not course_url:
        raise HTTPException(status_code=400, detail=f"Race {rc} is missing a URL in the plan.")

    try:
        # Using H-5 as the default phase for a manual run
        analysis_result = await analysis_pipeline.run_analysis_for_phase(
            course_url=course_url,
            phase="H-5",
            date=date_str,
            race_doc_id=doc_id,
        )
        firestore_client.update_race_document(doc_id, analysis_result)
        logger.info(f"Successfully processed and saved manual run for {doc_id}")
        return {
            "status": "success",
            "document_id": doc_id,
            "gpi_decision": analysis_result.get("gpi_decision", "N/A"),
        }
    except Exception as e:
        logger.error(f"Critical error during manual run for {doc_id}: {e}", exc_info=True)
        error_data = {
            "last_analyzed_at": datetime.now(timezone.utc).isoformat(),
            "phase": "H-5-manual",
            "status": "error",
            "error_message": str(e),
            "gpi_decision": "error_manual_run",
        }
        firestore_client.update_race_document(doc_id, error_data)
        raise HTTPException(
            status_code=500, detail=f"Failed to process manual run for {doc_id}."
        ) from e




@app.get("/debug/config", tags=["Debug"])
async def debug_config():
    """
    DEBUGGING ENDPOINT.
    Returns non-sensitive configuration values, including auth status,
    to help debug environment issues.
    """
    return {
        "require_auth": config.REQUIRE_AUTH,
        "internal_api_secret_is_set": bool(config.INTERNAL_API_SECRET),
        "internal_api_secret_first_chars": config.INTERNAL_API_SECRET[:4]
        if config.INTERNAL_API_SECRET
        else None,
        "project_id": config.PROJECT_ID,
        "bucket_name": config.BUCKET_NAME,
        "task_queue": config.TASK_QUEUE,
        "log_level": config.LOG_LEVEL,
        "timezone": config.TIMEZONE,
        "version": __version__,
    }


@app.get("/health", tags=["Monitoring"])
async def health_check():
    return {"status": "healthy", "version": __version__}


@app.get("/api/plan", tags=["API"])
async def get_daily_plan(date: str | None = None):
    """Returns the race plan for a given date."""
    try:
        date_str = date or datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")
        datetime.strptime(date_str, "%Y-%m-%d")  # Validate format
    except ValueError as e:
        raise HTTPException(
            status_code=422, detail="Invalid date format. Please use YYYY-MM-DD."
        ) from e

    daily_plan = await plan.build_plan_async(date_str)
    return {"ok": True, "date": date_str, "races": daily_plan, "count": len(daily_plan)}


@app.get("/api/schedule/next", tags=["API"])
async def get_next_scheduled_tasks():
    """Returns the next scheduled analysis tasks."""
    # This is a stub to fulfill the UI's request.
    # In a real implementation, this would query a task queue or database.
    return {
        "ok": False,
        "message": (
            "La fonctionnalité de consultation des tâches futures n'est pas encore implémentée."
        ),
        "tasks": [],
    }


# --- Task Worker Endpoint ---
class RaceTaskPayload(BaseModel):
    course_url: str
    phase: str
    date: str
    # Robust identifiers (preferred over URL parsing)
    r_label: str | None = None
    c_label: str | None = None
    doc_id: str | None = None


@app.post("/tasks/run-phase", tags=["Tasks"])
async def run_phase_worker(
    payload: RaceTaskPayload, request: Request, token_claims: dict = Security(verify_oidc_token)
):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    logger.info("Received task to run phase.", extra={"payload": payload.dict()})
    # Prefer explicit doc_id, then (date + r_label/c_label), then URL parsing as last resort.
    doc_id = payload.doc_id
    if not doc_id and payload.r_label and payload.c_label:
        doc_id = f"{payload.date}_{payload.r_label}{payload.c_label}"
    if not doc_id:
        doc_id = firestore_client.get_doc_id_from_url(payload.course_url, payload.date)

    try:
        # This is the actual call to the analysis pipeline
        analysis_result = await analysis_pipeline.run_analysis_for_phase(
            course_url=payload.course_url,
            phase=payload.phase,
            date=payload.date,
            race_doc_id=doc_id,
            correlation_id=correlation_id,
        )

        # The pipeline is responsible for creating the full document to save
        firestore_client.update_race_document(doc_id, analysis_result)

        logger.info(f"Successfully processed and saved analysis for {doc_id}")
        return {
            "status": "success",
            "document_id": doc_id,
            "gpi_decision": analysis_result.get("gpi_decision", "N/A"),
        }

    except Exception as e:
        logger.error(f"Critical error processing task for {doc_id}: {e}", exc_info=True)
        error_data = {
            "last_analyzed_at": datetime.now(timezone.utc).isoformat(),
            "phase": payload.phase,
            "status": "error",
            "error_message": str(e),
            "gpi_decision": "error_critical",
        }
        # Save error state to Firestore to prevent retries on permanent failures
        firestore_client.update_race_document(doc_id, error_data)
        # Raise an exception to signal failure to Cloud Tasks
        raise HTTPException(
            status_code=500, detail=f"Failed to process task for {doc_id}. See logs for details."
        ) from e
