import time
import uuid
import logging
from fastapi import Request
from .logging_utils import correlation_id_var, get_logger

logger = get_logger(__name__)

async def logging_middleware(request: Request, call_next):
    """
    Middleware to log requests, add a correlation ID, and measure latency.
    """
    start_time = time.time()
    
    # Generate a unique ID for this request and set it in the context variable
    request_id = str(uuid.uuid4())
    correlation_id_var.set(request_id)
    
    logger.info(
        "Request started",
        extra={
            "http_method": request.method,
            "http_path": request.url.path,
            "remote_addr": request.client.host,
            "user_agent": request.headers.get("user-agent"),
        },
    )
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Correlation-ID"] = request_id
        
        logger.info(
            "Request finished",
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": response.status_code,
                "process_time_ms": round(process_time * 1000, 2),
            },
        )
        return response

    except Exception as e:
        process_time = time.time() - start_time
        logger.exception(
            "Request failed with an unhandled exception",
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "process_time_ms": round(process_time * 1000, 2),
            },
        )
        # Re-raise the exception to be handled by FastAPI's default exception handling
        raise e

