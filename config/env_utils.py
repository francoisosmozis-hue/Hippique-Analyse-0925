"""Helpers for reading environment variables with validation.

This module provides :func:`get_env` which retrieves an environment
variable with optional type casting and default values. When the variable
is missing a warning is emitted; when a value is provided it logs that the
configuration has been overridden.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, TypeVar, Optional

T = TypeVar("T")


logger = logging.getLogger(__name__)


def get_env(
    name: str,
    default: Optional[T] = None,
    *,
    cast: Callable[[str], T] = lambda x: x,  # type: ignore[assignment]
    required: bool = False,
) -> T:
    """Fetch *name* from the environment with validation.

    Parameters
    ----------
    name:
        Name of the environment variable.
    default:
        Fallback value when the variable is missing.
    cast:
        Callable used to convert the raw string to the expected type.
    required:
        When ``True`` a missing variable triggers a ``RuntimeError``.

    Returns
    -------
    T
        The environment variable converted to the desired type or ``default``.
    """
    raw = os.getenv(name)
    if raw is None or raw == "":
        if required:
            raise RuntimeError(f"Missing required environment variable '{name}'")
        if default is not None:
            logger.warning("Environment variable %s not set, using default %r", name, default)
            return default
        logger.warning("Environment variable %s not set", name)
        return default  # type: ignore[return-value]
    try:
        value = cast(raw)
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            f"Invalid value for environment variable '{name}': {raw!r}"
        ) from exc
    if default is not None and value != default:
        logger.info("Environment variable %s=%r overrides default %r", name, value, default)
    return value
