import logging
import sys
from contextvars import ContextVar
import uuid

# Context variables for correlation and trace IDs
correlation_id_var = ContextVar("correlation_id", default=None)
trace_id_var = ContextVar("trace_id", default=None)

# This is a temporary, ultra-simple logging setup to diagnose startup crashes.
# It avoids all Google Cloud client libraries.

def setup_logging(log_level: str | None = "INFO"):
    """
    Configures a basic stdout logger.
    """
    # Use basicConfig which is simpler and safer for this test
    logging.basicConfig(
        level=(log_level or "INFO").upper(),
        stream=sys.stdout,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    logging.getLogger(__name__).info(f"Using basic stdout logging at level {(log_level or 'INFO').upper()}.")


def get_logger(name: str) -> logging.Logger:
    """Returns a logger with the given name."""
    return logging.getLogger(name)


def generate_trace_id():
    """Generates a unique trace ID."""
    return str(uuid.uuid4())
