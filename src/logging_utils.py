"""Structured logging utilities for Cloud Logging."""
import logging
import json
import sys
import uuid
from contextvars import ContextVar
from typing import Any, Dict


# Context variable for correlation ID
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Get or create correlation ID for current context."""
    cid = correlation_id_var.get()
    if not cid:
        cid = str(uuid.uuid4())
        correlation_id_var.set(cid)
    return cid


class StructuredFormatter(logging.Formatter):
    """JSON formatter for Cloud Logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "message": record.getMessage(),
            "severity": record.levelname,
            "timestamp": self.formatTime(record, self.datefmt),
            "logger": record.name,
        }
        
        # Add correlation ID if available
        cid = correlation_id_var.get()
        if cid:
            log_obj["correlation_id"] = cid
        
        # Add extra fields
        if hasattr(record, "extra"):
            log_obj.update(record.extra)
        
        # Add exception info
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_obj)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure structured logging for Cloud Run."""
    logger = logging.getLogger()
    logger.setLevel(level)
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Add structured handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    
    return logger
