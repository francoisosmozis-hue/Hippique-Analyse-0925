import logging
import sys
import uuid
from contextvars import ContextVar

from pythonjsonlogger import jsonlogger

# Context variables for correlation and trace IDs
correlation_id_var = ContextVar("correlation_id", default=None)
trace_id_var = ContextVar("trace_id", default=None)


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record['correlation_id'] = correlation_id_var.get()
        log_record['trace_id'] = trace_id_var.get()
        if not log_record.get('timestamp'):
            log_record['timestamp'] = record.created
        if not log_record.get('severity'):
            log_record['severity'] = record.levelname


def setup_logging(log_level: str | None = "INFO"):
    """
    Configures a structured JSON logger that outputs to stdout.
    """
    logger = logging.getLogger()
    logger.setLevel((log_level or "INFO").upper())

    # Prevent duplicate handlers if called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    # Format for structured logging in Google Cloud
    # severity and message are standard fields recognized by Cloud Logging
    formatter = CustomJsonFormatter('%(timestamp)s %(severity)s %(name)s %(message)s')

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Adjust logging for noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        f"Structured JSON logging configured at level {(log_level or 'INFO').upper()}."
    )


def get_logger(name: str) -> logging.Logger:
    """Returns a logger with the given name."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG) # Explicitly set level to DEBUG
    return logger


def generate_trace_id():
    """Generates a unique trace ID."""
    return str(uuid.uuid4())
