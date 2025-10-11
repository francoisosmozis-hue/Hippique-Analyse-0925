"""Utilities for configuring Google Cloud Storage synchronisation toggles."""

from __future__ import annotations

import os

GCS_TOGGLE_ENV = "USE_GCS"
LEGACY_TOGGLE_ENV = "USE_DRIVE"
_FALSE_VALUES = {"0", "false", "no", "off"}


def _normalise(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower()


def is_gcs_enabled(*, default: bool = True) -> bool:
    """Return ``True`` when Google Cloud synchronisation should run."""

    raw = _normalise(os.getenv(GCS_TOGGLE_ENV))
    if raw is not None:
        return raw not in _FALSE_VALUES
    legacy = _normalise(os.getenv(LEGACY_TOGGLE_ENV))
    if legacy is not None:
        return legacy == "true"
    return default


def disabled_reason() -> str | None:
    """Return the environment variable responsible for disabling uploads."""

    raw = _normalise(os.getenv(GCS_TOGGLE_ENV))
    if raw in _FALSE_VALUES:
        return GCS_TOGGLE_ENV
    legacy = _normalise(os.getenv(LEGACY_TOGGLE_ENV))
    if legacy in {"false", "0"}:
        return LEGACY_TOGGLE_ENV
    return None
