import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .logging_utils import correlation_id_var, get_correlation_id, get_logger

logger = get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        correlation_id = get_correlation_id(dict(request.headers))
        request.state.correlation_id = correlation_id
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            process_time = time.time() - start_time
            logger.info(
                "request_completed",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "process_time_ms": round(process_time * 1000, 2),
                    "status_code": response.status_code,
                },
            )
            return response
        except Exception:
            process_time = time.time() - start_time
            logger.exception(
                "request_failed",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "process_time_ms": round(process_time * 1000, 2),
                },
            )
            raise
        finally:
            correlation_id_var.reset(token)
