"""Lightweight HTTP entry points for the cloud runner.

The production project historically exposed a small Flask application used by
Google Cloud Functions.  The original entry point returned the same JSON tuple
structure expected by :mod:`tests.test_cloud_app`.  A recent refactor migrated
the codebase to FastAPI, however the simplified test harness – and a few
automation scripts – still rely on the legacy callable.  Re-introducing a small
compatibility layer keeps the refactor in place for the real deployment while
preserving the behaviour required by the tests.

``run_hminus`` mirrors the former Flask handler: it accepts either a ``dict`` or
an object exposing ``get_json`` (as provided by Flask requests), validates the
payload and calls the validator script via :func:`subprocess.run`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
"""Project root used as the working directory for subprocess calls."""

DATA_ROOT = ROOT / "data"
"""Base directory storing artefacts produced by the pipeline."""

VALIDATOR_SCRIPT = ROOT / "validator_ev.py"
"""Path to the validator script executed by :func:`run_hminus`."""

_JSON_HEADERS = {"Content-Type": "application/json"}
_VALID_PHASES = {"H30", "H5"}


def _json_response(
    payload: Mapping[str, Any], status: int
) -> tuple[str, int, dict[str, str]]:
    """Return a tuple compatible with the legacy Cloud Function contract."""

    return json.dumps(dict(payload), ensure_ascii=False), status, dict(_JSON_HEADERS)


def _coerce_payload(obj: Any) -> Mapping[str, Any]:
    """Extract a JSON payload from ``obj``.

    ``obj`` can be either a mapping (``dict``) or a Flask request-like object
    providing a ``get_json`` method.  Any unexpected type triggers ``TypeError``
    which is handled by :func:`run_hminus`.
    """

    if isinstance(obj, Mapping):
        return obj
    if hasattr(obj, "get_json"):
        getter = obj.get_json
        try:
            payload = getter(silent=True)  # type: ignore[call-arg]
        except TypeError:
            payload = getter()
        return payload or {}
    raise TypeError("Unsupported payload source")


def _normalise_label(value: Any, prefix: str) -> str | None:
    """Return a canonical ``R#``/``C#`` label when ``value`` is valid."""

    if not isinstance(value, str):
        return None
    trimmed = value.strip().upper().replace(" ", "")
    if not trimmed.startswith(prefix):
        return None
    suffix = trimmed[len(prefix) :]
    return trimmed if suffix.isdigit() and suffix else None


def _normalise_phase(value: Any) -> str | None:
    """Return a canonical phase (``H30``/``H5``) when ``value`` is valid."""

    if not isinstance(value, str):
        return None
    cleaned = value.strip().upper().replace("-", "")
    return cleaned if cleaned in _VALID_PHASES else None


def run_hminus(request: Any) -> tuple[str, int, dict[str, str]]:
    """Entry point used by the H-30/H-5 automation flow.

    The handler validates the payload and executes ``validator_ev.py``.  Errors
    are reported as JSON responses consistent with the original Flask
    implementation.
    """

    try:
        payload = _coerce_payload(request)
    except TypeError:
        return _json_response({"ok": False, "error": "invalid_payload"}, status=400)

    r_label = _normalise_label(payload.get("R") or payload.get("reunion"), "R")
    c_label = _normalise_label(payload.get("C") or payload.get("course"), "C")
    phase = _normalise_phase(payload.get("when") or payload.get("phase"))

    if not (r_label and c_label and phase):
        return _json_response({"ok": False, "error": "invalid_payload"}, status=400)

    artefacts = DATA_ROOT / f"{r_label}{c_label}"
    cmd = [
        sys.executable,
        str(VALIDATOR_SCRIPT),
        "--artefacts",
        str(artefacts),
        "--phase",
        phase,
    ]

    try:
        subprocess.run(cmd, check=True, cwd=str(ROOT))
    except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
        return _json_response(
            {"ok": False, "error": "validator_failed", "returncode": exc.returncode},
            status=500,
        )

    return _json_response({"ok": True}, status=200)


__all__ = ["run_hminus", "ROOT", "DATA_ROOT", "VALIDATOR_SCRIPT"]
