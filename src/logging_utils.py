"""
src/logging_utils.py - Logs Structurés JSON

Logs structurés pour Cloud Logging avec severity, timestamp, correlation_id.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional

class StructuredLogger:
    """Logger with JSON-structured output for Cloud Logging"""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(name)
        
        # Configure logger
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
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
<<<<<<< HEAD
=======
        # Sanitize exception objects

        for k, v in list(log_entry.items()):

            if hasattr(v, "__class__") and "Exception" in v.__class__.__name__:

                log_entry[k] = str(v)

        

>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
        print(json.dumps(log_entry), flush=True)
    
    def debug(self, message: str, **kwargs: Any) -> None:
        """Log DEBUG level"""
        self._log("DEBUG", message, **kwargs)
    
    def info(self, message: str, **kwargs: Any) -> None:
        """Log INFO level"""
        self._log("INFO", message, **kwargs)
    
    def warning(self, message: str, **kwargs: Any) -> None:
        """Log WARNING level"""
        self._log("WARNING", message, **kwargs)
    
    def error(self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any) -> None:
        """Log ERROR level"""
        if exc_info:
            import traceback
            kwargs["traceback"] = traceback.format_exc()
        self._log("ERROR", message, **kwargs)
    
    def critical(self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any) -> None:
        """Log CRITICAL level"""
        if exc_info:
            import traceback
            kwargs["traceback"] = traceback.format_exc()
        self._log("CRITICAL", message, **kwargs)

# Cache loggers
_loggers: Dict[str, StructuredLogger] = {}

def get_logger(name: str) -> StructuredLogger:
    """Get or create a structured logger"""
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name)
<<<<<<< HEAD
    return _loggers[name]
=======
    return _loggers[name]
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
