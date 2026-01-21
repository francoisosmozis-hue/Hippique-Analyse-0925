import contextvars
import logging
import uuid

correlation_id_var = contextvars.ContextVar("correlation_id", default="N/A")


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def get_correlation_id(request_headers: dict | None = None) -> str:
    headers = {str(k).lower(): v for k, v in (request_headers or {}).items()}
    cid = headers.get("x-correlation-id")
    if cid:
        return str(cid)
    return str(uuid.uuid4())
