from __future__ import annotations

import json
import subprocess
import sys
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "analyse_courses_du_jour_enrichie.py"
_VALID_PHASES = {"H30", "H5"}


def _make_response(payload: Mapping[str, Any], status: int = 200) -> tuple[str, int, dict[str, str]]:
    """Return a Flask-compatible JSON response tuple."""

    return json.dumps(dict(payload)), status, {"Content-Type": "application/json"}


def _extract_payload(request: Any) -> Mapping[str, Any]:
    """Extract a JSON object from ``request``.

    ``request`` may be a Flask ``Request`` object, a dictionary (useful for unit
    tests) or any object exposing a ``data`` attribute containing a JSON string.
    """

    if request is None:
        return {}
    if isinstance(request, Mapping):
        return request

    get_json = getattr(request, "get_json", None)
    if callable(get_json):
        payload = get_json(silent=True)
        if payload is None:
            return {}
        if isinstance(payload, Mapping):
            return payload
        raise ValueError("Le corps JSON doit être un objet.")

    raw_json = getattr(request, "json", None)
    if isinstance(raw_json, Mapping):
        return raw_json

    data = getattr(request, "data", None)
    if data is None:
        return {}
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    if isinstance(data, str):
        data = data.strip()
        if not data:
            return {}
        try:
            payload = json.loads(data)
        except JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Payload JSON invalide: {exc}") from exc
        if isinstance(payload, Mapping):
            return payload
        raise ValueError("Le payload JSON doit être un objet.")

    raise ValueError("Impossible de décoder le payload de la requête.")


def _extract_key(payload: Mapping[str, Any], *names: str) -> Any:
    """Return the first matching key from ``payload`` among ``names``."""

    for name in names:
        for candidate in (name, name.lower(), name.upper()):
            if candidate in payload:
                return payload[candidate]
    if len(names) == 1:
        raise ValueError(f"Champ {names[0]} manquant dans le payload")
    joined = "/".join(names)
    raise ValueError(f"Champ {joined} manquant dans le payload")


def _normalise_label(value: Any, prefix: str) -> str:
    """Normalise a race label such as ``R1`` or ``C3``."""

    text = str(value).strip().upper().replace(" ", "")
    if not text:
        raise ValueError(f"Identifiant {prefix} vide")
    if text.startswith(prefix):
        text = text[len(prefix) :]
    elif text.startswith(prefix[0]):
        text = text[1:]
    if not text.isdigit():
        raise ValueError(f"Identifiant {prefix} invalide: {value!r}")
    number = int(text)
    if number <= 0:
        raise ValueError(f"Identifiant {prefix} invalide: {value!r}")
    return f"{prefix}{number}"


def _normalise_phase(value: Any) -> str:
    """Return ``H30`` or ``H5`` from user-supplied ``value``."""

    if not isinstance(value, str):
        raise ValueError(f"Phase inconnue: {value!r} (attendu H30 ou H5)")
    cleaned = value.strip().upper().replace("-", "").replace(" ", "")
    if cleaned not in _VALID_PHASES:
        raise ValueError(f"Phase inconnue: {value!r} (attendu H30 ou H5)")
    return cleaned


def _build_command(payload: Mapping[str, Any]) -> list[str]:
    """Translate ``payload`` into the CLI call for the analyser script."""

    reunion = _normalise_label(_extract_key(payload, "R", "reunion"), "R")
    course = _normalise_label(_extract_key(payload, "C", "course"), "C")
    phase = _normalise_phase(_extract_key(payload, "when", "phase"))
    return [
        sys.executable,
        str(SCRIPT),
        "--reunion",
        reunion,
        "--course",
        course,
        "--phase",
        phase,
    ]


def run_hminus(request: Any) -> tuple[str, int, dict[str, str]]:
    """HTTP entry-point handling ``/run/hminus`` invocations."""

    try:
        payload = _extract_payload(request)
        command = _build_command(payload)
    except ValueError as exc:
        return _make_response({"ok": False, "error": str(exc)}, status=400)

    try:
        subprocess.run(command, check=True, cwd=str(ROOT))
    except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
        return _make_response(
            {"ok": False, "error": f"analyse_courses_du_jour_enrichie a échoué ({exc.returncode})"},
            status=500,
        )

    return _make_response({"ok": True})


try:  # pragma: no cover - optional dependency
    from flask import Flask, request as flask_request
except Exception:  # pragma: no cover - Flask isn't required for the tests
    Flask = None  # type: ignore
    flask_request = None  # type: ignore


if Flask is not None:  # pragma: no cover - exercised in production
    flask_app = Flask(__name__)

    @flask_app.post("/run/hminus")
    def _run_hminus_endpoint() -> tuple[str, int, dict[str, str]]:
        return run_hminus(flask_request)

    app = flask_app
else:  # pragma: no cover - exported for consistency
    app = None
