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
) -> T:
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
        When ``True`` a missing variable triggers a ``RuntimeError``.

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
            raise RuntimeError(f"Missing required environment variable '{name}'")
        logger.warning("Environment variable %s not set; using default %r", name, default)
        return default  # type: ignore[return-value]

    try:
        value = cast(raw_value)
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            f"Invalid value for environment variable '{name}': {raw_value!r}"
        ) from exc

    if source != name:
        logger.info("Environment variable %s=%r used as alias for %s", source, value, name)

    if default is not None and value != default:
        logger.info("Environment variable %s=%r overrides default %r", source, value, default)
    return value
