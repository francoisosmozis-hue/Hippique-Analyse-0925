"""
src/logging_utils.py - Configuration des logs structurés pour Cloud Logging
"""

import json
import logging
import sys
import traceback
from datetime import datetime
from typing import Any

from app_config import get_config


class StructuredLogger(logging.Logger):
    """Logger qui émet des logs au format JSON structuré."""

    def _log_structured(
        self,
        level: int,
        msg: str,
        *,
        extra: dict[str, Any] | None = None,
        exc_info: Any = None,
        **kwargs: Any
    ) -> None:
        """Émet un log structuré JSON."""

        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "severity": logging.getLevelName(level),
            "message": str(msg),
            "logger": self.name,
        }

        # Ajouter extra fields
        if extra:
            record.update(extra)

        # Ajouter kwargs
        for key, value in kwargs.items():
            if key not in record:
                record[key] = value

        # Ajouter exception info
        if exc_info:
            if isinstance(exc_info, BaseException):
                exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
            elif exc_info is True:
                exc_info = sys.exc_info()

            if exc_info and exc_info[0] is not None:
                record["exception"] = {
                    "type": exc_info[0].__name__,
                    "message": str(exc_info[1]),
                    "stacktrace": "".join(traceback.format_exception(*exc_info)),
                }

        # Émettre le log JSON
        print(json.dumps(record, default=str), file=sys.stdout, flush=True)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log DEBUG structuré."""
        if self.isEnabledFor(logging.DEBUG):
            self._log_structured(logging.DEBUG, msg % args if args else msg, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log INFO structuré."""
        if self.isEnabledFor(logging.INFO):
            self._log_structured(logging.INFO, msg % args if args else msg, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log WARNING structuré."""
        if self.isEnabledFor(logging.WARNING):
            self._log_structured(logging.WARNING, msg % args if args else msg, **kwargs)

    def error(self, msg: str, *args: Any, exc_info: Any = None, **kwargs: Any) -> None:
        """Log ERROR structuré."""
        if self.isEnabledFor(logging.ERROR):
            self._log_structured(
                logging.ERROR,
                msg % args if args else msg,
                exc_info=exc_info,
                **kwargs
            )

    def critical(self, msg: str, *args: Any, exc_info: Any = None, **kwargs: Any) -> None:
        """Log CRITICAL structuré."""
        if self.isEnabledFor(logging.CRITICAL):
            self._log_structured(
                logging.CRITICAL,
                msg % args if args else msg,
                exc_info=exc_info,
                **kwargs
            )


def setup_logging() -> None:
    """Configure le logging global pour le service."""
    config = get_app_config()

    # Définir le niveau global
    level = getattr(logging, config.log_level, logging.INFO)

    # Remplacer la classe Logger par défaut
    logging.setLoggerClass(StructuredLogger)

    # Configurer le root logger
    root = logging.getLogger()
    root.setLevel(level)

    # Supprimer les handlers par défaut
    root.handlers.clear()

    # Ajouter un handler simple (print JSON)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(message)s"))  # Pas de formatage supplémentaire
    root.addHandler(handler)

    # Réduire la verbosité des librairies tierces
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)


def get_logger(name: str) -> StructuredLogger:
    """Retourne un logger structuré pour le module donné."""
    return logging.getLogger(name)  # type: ignore


def log_request(
    method: str,
    path: str,
    status: int,
    duration_ms: float,
    correlation_id: str | None = None,
    **extra: Any
) -> None:
    """Log une requête HTTP."""
    logger = get_logger("http")
    logger.info(
        f"{method} {path} {status}",
        method=method,
        path=path,
        status=status,
        duration_ms=round(duration_ms, 2),
        correlation_id=correlation_id,
        **extra
    )
