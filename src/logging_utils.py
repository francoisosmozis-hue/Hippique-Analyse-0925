"""Logging utilities for structured output compatible with Cloud Logging."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_RESERVED_FIELDS = {
    "msg",
    "args",
    "levelname",
    "levelno",
    "created",
    "msecs",
    "relativeCreated",
    "pathname",
    "filename",
    "module",
    "lineno",
    "funcName",
    "stack_info",
    "exc_text",
    "exc_info",
}


class JsonFormatter(logging.Formatter):
    """Format log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 - short description
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "logger": record.name,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key.startswith("_"):
                continue
            if key in payload or key in _RESERVED_FIELDS:
                continue
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger to use JSON formatting."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    logging.basicConfig(level=level, handlers=[handler], force=True)


def get_logger(name: str) -> logging.Logger:
    """Get a structured logger."""

    logger = logging.getLogger(name)
    if not logger.handlers:
        setup_logging()
    return logger


def log_exception(
    logger: logging.Logger, message: str, *, extra: dict[str, Any] | None = None
) -> None:
    """Log an exception with structured context."""

    logger.exception(message, extra=extra or {})
