"""Utilities for configuring Google Cloud Storage synchronisation toggles."""

from __future__ import annotations

from hippique_orchestrator import config


def is_gcs_enabled(*, default: bool = True) -> bool:
    """Return ``True`` when Google Cloud synchronisation should run."""
    return config.GCS_ENABLED


def disabled_reason() -> str | None:
    """Return the environment variable responsible for disabling uploads."""
    if not config.GCS_ENABLED:
        return "GCS_ENABLED is False"
    return None
