import json
from datetime import datetime


class StructuredLogger:
    """Logger JSON structuré pour Cloud Logging."""

    def __init__(self, name: str):
        self.name = name

    def _log(self, severity: str, message: str, **kwargs):
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "severity": severity,
            "message": message,
            "component": self.name,
            **kwargs
        }
        print(json.dumps(entry), flush=True)

    def info(self, message: str, **kwargs):
        self._log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log("ERROR", message, **kwargs)

    def debug(self, message: str, **kwargs):
        self._log("DEBUG", message, **kwargs)


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)
