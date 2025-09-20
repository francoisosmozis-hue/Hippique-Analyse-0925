"""Compatibility module exposing the FastAPI app from ``hippique-app``."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "hippique-app" / "main.py"
_spec = spec_from_file_location("hippique_app_main", _MODULE_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive guard
    raise RuntimeError(f"Impossible de charger l'application depuis {_MODULE_PATH}")

_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)
app = getattr(_module, "app")
