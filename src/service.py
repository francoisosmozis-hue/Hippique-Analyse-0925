"""
src/service.py - FastAPI Service Principal
"""

from __future__ import annotations

import sys, pathlib
ROOT = str(pathlib.Path(__file__).resolve().parents[1])
if ROOT not in sys.path: sys.path.insert(0, ROOT)

import uuid
from datetime import datetime

from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import JSONResponse

from app_config import get_config
from logging_utils import get_logger
from src.pipeline_routes import router as pipeline_router

print("DEBUG: Getting config...")
config = get_config()
print("DEBUG: Config loaded.")
print("DEBUG: Getting logger...")
logger = get_logger(__name__)
print("DEBUG: Logger loaded.")

print("DEBUG: Creating FastAPI app...")
app = FastAPI(
    title="Hippique Orchestrator",
    description="Cloud Run service for automated horse racing analysis (GPI v5.1)",
    version="2.0.0",
)
print("DEBUG: FastAPI app created.")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    logger.info(f"{request.method} {request.url.path}", correlation_id=correlation_id, method=request.method, path=request.url.path, client=request.client.host if request.client else "unknown")
    request.state.correlation_id = correlation_id
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    except Exception as e:
        logger.error(f"Request failed: {e}", correlation_id=correlation_id, exc_info=e)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Internal server error", "correlation_id": correlation_id}, headers={"X-Correlation-ID": correlation_id})

@app.middleware("http")
async def verify_oidc_token(request: Request, call_next):
    if request.url.path == "/healthz":
        return await call_next(request)
    if not config.require_auth:
        return await call_next(request)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        logger.warning("Missing or invalid Authorization header")
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"error": "Missing or invalid Authorization header"})
    token = auth_header[7:]
    if not token or len(token) < 10:
        logger.warning("Invalid OIDC token")
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"error": "Invalid OIDC token"})
    logger.debug("OIDC token validated")
    return await call_next(request)

@app.get("/healthz")
async def health_check():
    return {"status": "healthy", "service": "hippique-orchestrator", "version": "2.0.0", "timestamp": datetime.utcnow().isoformat() + "Z"}

print("DEBUG: Including router...")
app.include_router(pipeline_router, prefix="/pipeline", tags=["pipeline"])
print("DEBUG: Router included.")

@app.on_event("startup")
async def startup_event():
    logger.info("Service starting", version="2.0.0", project_id=config.project_id, region=config.region)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Service shutting down")

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.warning(f"HTTP {exc.status_code}: {exc.detail}", correlation_id=correlation_id, status_code=exc.status_code)
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "correlation_id": correlation_id})

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.error(f"Unhandled exception: {exc}", correlation_id=correlation_id, exc_info=exc)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Internal server error", "correlation_id": correlation_id})