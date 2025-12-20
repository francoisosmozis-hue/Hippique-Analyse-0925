import json
import logging
import sys
import traceback
from datetime import datetime

from hippique_orchestrator.config import get_config  # Import get_config


class JsonFormatter(logging.Formatter):
    """Formats log records as JSON for Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "logger": record.name,
        }

        # The LogRecord already has 'extra' fields if passed by logger.info(msg, extra={...})
        # We need to copy these to our log_entry
        for key, value in record.__dict__.items():
            if key not in [
                'name',
                'msg',
                'levelname',
                'levelno',
                'pathname',
                'filename',
                'lineno',
                'funcName',
                'created',
                'msecs',
                'relativeCreated',
                'thread',
                'threadName',
                'processName',
                'process',
                'exc_info',
                'exc_text',
                'stack_info',
                'args',
                'module',
                'asctime',
            ] and not key.startswith('_'):
                log_entry[key] = value

        # Add exception info if present
        if record.exc_info:
            log_entry["traceback"] = "".join(traceback.format_exception(*record.exc_info))

        return json.dumps(log_entry)


_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger configured to output structured JSON."""
    if name not in _loggers:
        logger = logging.getLogger(name)

        if logger.hasHandlers():
            logger.handlers.clear()

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())

        logger.addHandler(handler)

        # Dynamically set level from config
        app_config = get_config()  # Get the config
        logger.setLevel(app_config.LOG_LEVEL.upper())  # Set level based on config

        logger.propagate = False

        _loggers[name] = logger

    return _loggers[name]
