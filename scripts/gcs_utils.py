<<<<<<< HEAD
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
=======
from __future__ import annotations
import os

def is_gcs_enabled() -> bool:
    """
    Active GCS si un bucket est défini ET si on a des identifiants valides.
    Tu peux simplifier le critère selon ton infra.
    """
    bucket = os.getenv("GCS_BUCKET", "").strip()
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    return bool(bucket) and (os.path.exists(creds) if creds else True)

def disabled_reason() -> str:
    reasons = []
    if not os.getenv("GCS_BUCKET"):
        reasons.append("GCS_BUCKET non défini")
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if creds and not os.path.exists(creds):
        reasons.append(f"Fichier d'identifiants introuvable: {creds}")
    if not reasons:
        reasons.append("GCS désactivé par configuration locale")
    return " / ".join(reasons)
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
