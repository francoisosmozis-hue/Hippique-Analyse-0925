"""Utilities for reading environment-backed configuration values."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


logger = logging.getLogger(__name__)


def _iter_candidates(name: str, aliases: Sequence[str] | None) -> list[str]:
    """Return the ordered list of environment variable names to inspect."""

    if not aliases:
        return [name]
    return [name, *aliases]


def get_env(
    name: str,
    default: T | None = None,
    *,
    cast: Callable[[str], T] = lambda x: x,  # type: ignore[assignment]
    required: bool = False,
    aliases: Sequence[str] | None = None,
) -> T | None:
    """Fetch an environment variable and coerce it to the desired type.

    Parameters
    ----------
    name:
        Canonical name of the environment variable to resolve.
    default:
        Fallback value returned when the variable is not present.
    cast:
        Callable used to convert the raw string value to ``T``.
    required:
        When ``True``, logs a critical error if the variable is missing.

    aliases:
        Optional iterable of alternative environment variable names.
    """

    raw_value: str | None = None
    source = name
    for candidate in _iter_candidates(name, aliases):
        candidate_val = os.getenv(candidate)
        if candidate_val in (None, ""):
            continue
        raw_value = candidate_val
        source = candidate
        break

    if raw_value is None:
        if required:
            # Instead of raising, log a critical error.
            # This allows the app to start so we can debug config via the API.
            logger.critical(
                "Missing required environment variable '%s'. App may not function correctly.", name
            )
        else:
            logger.warning("Environment variable %s not set; using default %r", name, default)

        return default

    try:
        value = cast(raw_value)
    except Exception:  # pragma: no cover - defensive
        logger.error(
            "Invalid value for environment variable '%s': %r. Returning default.",
            name,
            raw_value,
            exc_info=True,
        )
        # In case of casting error on a required var, it's better to return default
        # to avoid a crash, and let the debug endpoint reveal the problem.
        return default

    if source != name:
        logger.info("Environment variable %s=%r used as alias for %s", source, value, name)

    if default is not None and value != default:
        logger.info("Environment variable %s=%r overrides default %r", source, value, default)
    return value
