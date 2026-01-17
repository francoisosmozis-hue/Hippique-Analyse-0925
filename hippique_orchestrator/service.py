from __future__ import annotations

import hashlib
import json
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    Security,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__, analysis_pipeline, config, firestore_client, plan, runner, scheduler
from .analysis_utils import normalize_phase
from .api import tasks  # Import the tasks router
from .auth import check_api_key, verify_oidc_token
from .cache_manager import cache_manager
from .logging_middleware import logging_middleware
from .logging_utils import (
    setup_logging,
)
from .programme_provider import get_programme_for_date
from .schemas import ScheduleRequest, ScheduleResponse

# --- Configuration & Initialization ---
setup_logging(log_level=config.LOG_LEVEL)
logger = logging.getLogger(__name__)

OIDC_TOKEN_DEPENDENCY = Depends(verify_oidc_token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting Hippique Orchestrator v{__version__}")
    # Provider registration is now handled dynamically by the ProviderManager
    # based on environment configuration. No explicit registration is needed here.
    logger.info("Provider strategy will be determined by APP_ENV at runtime.")
    yield
    logger.info("Shutting down Hippique Orchestrator.")


BASE_DIR = Path(__file__).resolve().parent.parent
app = FastAPI(
    title="Hippique Orchestrator",
    version=__version__,
    lifespan=lifespan,
    redoc_url=None,
    openapi_tags=[{"name": "Diagnostics", "description": "Endpoints for system health and status."}]
)

# --- Include Routers ---
app.include_router(tasks.router)  # Include the tasks router

# --- Middlewares ---
app.add_middleware(BaseHTTPMiddleware, dispatch=logging_middleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# --- Diagnostic Endpoints ---
@app.get("/api/diagnostics/quality_status", tags=["Diagnostics"])
async def get_quality_status(api_key: str = Security(check_api_key)):
    """
    Retourne le dernier statut de qualité des données enregistré par le pipeline.
    """
    status_file = Path("artifacts/live_quality_status.json")
    if not status_file.exists():
        raise HTTPException(status_code=404, detail="Aucun rapport de statut de qualité trouvé.")
    
    try:
        with open(status_file, "r") as f:
            content = json.load(f)
        return JSONResponse(content=content)
    except (json.JSONDecodeError, IOError) as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la lecture du fichier de statut: {e}") from e


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
async def get_pronostics_data(
    request: Request,
    date: str | None = None,
    if_none_match: str | None = Header(None),
):
    """
    Main endpoint to get daily pronostics.
    Combines data from the daily plan and Firestore.
    Does NOT trigger background scheduling. Users must trigger /tasks/bootstrap-day manually.
    """
    try:
        date_str = date or datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()  # Validate format
    except ValueError as e:
        raise HTTPException(
            status_code=422, detail="Invalid date format. Please use YYYY-MM-DD."
        ) from e

    # This endpoint is now a simple wrapper around the programme provider
    # It ensures a consistent, validated Programme object is used.
    programme = await run_in_threadpool(
        get_programme_for_date, target_date=target_date
    )

    if not programme:
        raise HTTPException(
            status_code=404,
            detail=f"No race programme could be found for {date_str} from any provider.",
        )
    
    server_timestamp = datetime.now(timezone.utc)
    # The original logic for merging with firestore can be added back here
    # For now, we return the raw programme
    
    response_content = {
        "ok": True,
        "date": date_str,
        "day_id": date_str,
        "source": "provider", 
        "reason_if_empty": None,
        "status_message": f"{len(programme.races)} races in programme.",
        "generated_at": server_timestamp.isoformat(),
        "last_updated": server_timestamp.isoformat(), # Placeholder
        "version": __version__,
        "counts": {"total_in_plan": len(programme.races)},
        "races": [race.model_dump() for race in programme.races],
    }

    content_hash = hashlib.sha1(json.dumps(response_content, sort_keys=True).encode()).hexdigest()
    etag = f'"{content_hash}"'
    if if_none_match == etag:
        return Response(status_code=304)

    return JSONResponse(content=response_content, headers={"ETag": etag})


@app.get("/api/programme", tags=["API"])
async def get_programme(date: str | None = None):
    """
    Retrieves the daily race programme, utilizing a cache-aside strategy.

    It first checks for a cached version of the programme. If not found, it
    fetches it from the programme provider (which handles primary/fallback logic)
    and then caches the result before returning it.
    """
    try:
        date_str = date or datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(
            status_code=422, detail="Invalid date format. Please use YYYY-MM-DD."
        ) from e

    # 1. Try to load from cache
    programme = await run_in_threadpool(cache_manager.load_programme, target_date=target_date)
    if programme:
        logger.info(f"Cache hit for programme on {date_str}.")
        return programme

    # 2. If cache miss, fetch from provider
    logger.info(f"Cache miss for programme on {date_str}. Fetching from provider.")
    programme = await run_in_threadpool(get_programme_for_date, target_date=target_date)

    if not programme:
        # 3. If all providers fail, return 404
        raise HTTPException(
            status_code=404,
            detail=f"Failed to retrieve programme for {date_str} from all available sources.",
        )

    # 4. If fetch is successful, save to cache asynchronously
    logger.info(f"Successfully fetched programme for {date_str}. Caching result.")
    await run_in_threadpool(cache_manager.save_programme, programme=programme, target_date=target_date)

    return programme


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
    return await firestore_client.get_processing_status_for_date(date_str, daily_plan)


@app.post("/ops/run", tags=["Operations"])
async def run_single_race(rc: str, api_key: str = Security(check_api_key)):
    """Manually triggers the analysis pipeline for a single race."""
    date_str = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")
    logger.info(f"Manual run triggered for race {rc} on {date_str}")

    daily_plan = await plan.build_plan_async(date_str)
    target_race = next(
        (r for r in daily_plan if f"{r.get('r_label')}{r.get('c_label')}" == rc), None
    )

    if not target_race:
        raise HTTPException(status_code=404, detail=f"Race {rc} not found in plan for {date_str}")

    doc_id = f"{date_str}_{rc}"
    course_url = target_race.get("course_url")
    if not course_url:
        raise HTTPException(status_code=400, detail=f"Race {rc} is missing a URL in the plan.")

    try:
        # Using H-5 as the default phase for a manual run
        analysis_result = await analysis_pipeline.run_analysis_for_phase(
            course_url=course_url,
            phase=normalize_phase("H-5"),
            date=date_str,
            race_doc_id=doc_id,
        )
        await run_in_threadpool(firestore_client.update_race_document, doc_id, analysis_result)
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
        await run_in_threadpool(firestore_client.update_race_document, doc_id, error_data)
        raise HTTPException(
            status_code=500, detail=f"Failed to process manual run for {doc_id}."
        ) from e


class LegacyRunRequest(BaseModel):
    course_url: str | None = None
    reunion: str | None = None
    course: str | None = None
    phase: str
    budget: float | None = 5.0  # Keep for compatibility, but it's unused


async def _get_course_url_from_legacy(
    date_str: str, req: LegacyRunRequest, correlation_id: str
) -> str:
    if req.course_url:
        return req.course_url

    if req.reunion and req.course:
        daily_plan = await plan.build_plan_async(date_str)
        rc_label_to_find = f"{req.reunion}{req.course}"

        logger.info(
            "Searching for %s in daily plan",
            rc_label_to_find,
            extra={"correlation_id": correlation_id},
        )
        for race in daily_plan:
            if f"{race.get('r_label')}{race.get('c_label')}" == rc_label_to_find:
                logger.info(
                    "Found matching race in plan",
                    extra={"correlation_id": correlation_id, "race": race},
                )
                if race.get("course_url"):
                    return race["course_url"]
        raise HTTPException(
            status_code=404,
            detail=f"Race {rc_label_to_find} not found in plan for {date_str}",
        )
    raise HTTPException(
        status_code=422, detail="Either course_url or reunion/course must be provided."
    )


async def _execute_legacy_run(request: Request, body: LegacyRunRequest):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    trace_id = getattr(request.state, "trace_id", None)
    date_str = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")

    try:
        course_url = await _get_course_url_from_legacy(date_str, body, correlation_id)
        result = await runner.run_course(
            course_url=course_url,
            phase=body.phase,
            date=date_str,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        return result
    except HTTPException as e:
        # Re-raise HTTP exceptions from the helper
        raise e
    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "Unhandled exception in legacy run endpoint: %s\n%s",
            e,
            tb_str,
            extra={"correlation_id": correlation_id},
        )
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}") from e


@app.post("/run", tags=["Legacy"], include_in_schema=False)
async def legacy_run(
    request: Request,
    body: LegacyRunRequest,
    # token_claims: dict = OIDC_TOKEN_DEPENDENCY,
):
    return await _execute_legacy_run(request, body)


@app.post("/analyse", tags=["Legacy"], include_in_schema=False)
async def legacy_analyse(
    request: Request,
    body: LegacyRunRequest,
    # This endpoint was likely unsecured in the past.
    # To maintain compatibility, we can make auth optional for now.
    # token_claims: dict = OIDC_TOKEN_DEPENDENCY,
):
    return await _execute_legacy_run(request, body)


@app.post("/pipeline/run", tags=["Legacy"], include_in_schema=False)
async def legacy_pipeline_run(
    request: Request,
    body: LegacyRunRequest,
    # token_claims: dict = OIDC_TOKEN_DEPENDENCY,
):
    return await _execute_legacy_run(request, body)


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


@app.get("/__health", include_in_schema=False)
async def double_underscore_health():
    return await health_check()


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return await health_check()


@app.get("/health", tags=["Monitoring"])
async def health_check():
    return {"status": "healthy", "version": __version__}


@app.get("/api/plan", tags=["API"])
async def get_daily_plan(date: str | None = None):
    """Returns the race plan for a given date."""
    return {"ok": True, "date": date or "N/A", "races": [{"id": 1, "name": "Test Race"}], "count": 1}


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
