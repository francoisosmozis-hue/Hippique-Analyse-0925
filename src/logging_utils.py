"""
src/logging_utils.py - Logs Structurés JSON

Logs structurés pour Cloud Logging avec severity, timestamp, correlation_id.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import Any


class StructuredLogger:
    """Logger with JSON-structured output for Cloud Logging"""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(name)

        # Configure logger
        if self.logger.hasHandlers():
            self.logger.handlers.clear()
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.DEBUG)

    def _log(
        self,
        severity: str,
        message: str,
        **kwargs: Any
    ) -> None:
        """
        Log a structured message.

        Args:
            severity: "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
            message: Log message
            **kwargs: Additional fields (correlation_id, etc.)
        """
        log_entry = {
            "severity": severity,
            "message": message,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "logger": self.name,
        }

        # Add custom fields
        for key, value in kwargs.items():
            if value is not None:
                log_entry[key] = value

        # Print JSON line
        # Sanitize exception objects

        for k, v in list(log_entry.items()):

            if hasattr(v, "__class__") and "Exception" in v.__class__.__name__:

                log_entry[k] = str(v)

        print(json.dumps(log_entry), file=sys.stderr, flush=True)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log DEBUG level"""
        self._log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log INFO level"""
        self._log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log WARNING level"""
        self._log("WARNING", message, **kwargs)

    def error(self, message: str, exc_info: Exception | None = None, **kwargs: Any) -> None:
        """Log ERROR level"""
        if exc_info:
            import traceback
            kwargs["traceback"] = traceback.format_exc()
        self._log("ERROR", message, **kwargs)

    def critical(self, message: str, exc_info: Exception | None = None, **kwargs: Any) -> None:
        """Log CRITICAL level"""
        if exc_info:
            import traceback
            kwargs["traceback"] = traceback.format_exc()
        self._log("CRITICAL", message, **kwargs)

# Cache loggers
_loggers: dict[str, StructuredLogger] = {}

def get_logger(name: str) -> StructuredLogger:
    """Get or create a structured logger"""
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name)
    return _loggers[name]
