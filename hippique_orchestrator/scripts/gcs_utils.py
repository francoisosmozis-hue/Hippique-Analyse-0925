"""Utilities for configuring Google Cloud Storage synchronisation toggles."""
from __future__ import annotations

from hippique_orchestrator.config import get_config

config = get_config()

def is_gcs_enabled(*, default: bool = True) -> bool:
    """Return ``True`` when Google Cloud synchronisation should run."""
    if config.use_gcs is not None:
        return config.use_gcs
    if config.use_drive is not None:
        return config.use_drive
    return default


def disabled_reason() -> str | None:
    """Return the environment variable responsible for disabling uploads."""
    if config.use_gcs is False:
        return "USE_GCS"
    if config.use_drive is False:
        return "USE_DRIVE"
    return None
