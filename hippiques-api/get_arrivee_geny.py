#!/usr/bin/env python3
"""Fetch the official arrival for a Geny race.

This CLI wrapper is used by the :mod:`hippiques-api` service which shells out
to the historical :mod:`get_arrivee_geny` scraper located at the repository
root.  The original script expects a full daily planning file while the API
only knows the ``race_id`` (a Geny ``course_id``).  To avoid duplicating the
scraping code we dynamically load the repository level module and reuse its
``PlanningEntry``/``fetch_arrival_for_course`` helpers.

The resulting JSON payload mirrors the structure produced by the legacy Bash
pipelines so that downstream tooling keeps working:

.. code-block:: json

    {
      "race_id": "1602185",
      "status": "OK",
      "source": "geny",
      "fetched_at": "2025-09-20T10:58:00Z",
      "arrivee": ["7", "3", "1", "6", "5"]
    }
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

SCRAPER_MODULE_NAME = "_hippique_arrivee_scraper"


def _load_scraper_module() -> ModuleType:
    """Return the repository-level :mod:`get_arrivee_geny` module."""

    root_path = Path(__file__).resolve().parents[1] / "get_arrivee_geny.py"
    spec = importlib.util.spec_from_file_location(SCRAPER_MODULE_NAME, root_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"Unable to load scraper module from {root_path}")

    module = importlib.util.module_from_spec(spec)
    # Cache the module so repeated invocations do not reload the file.
    sys.modules[SCRAPER_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_SCRAPER_MODULE = _load_scraper_module()


def _get_scraper_helper(name: str) -> Any:
    try:
        return getattr(_SCRAPER_MODULE, name)
    except AttributeError as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"Scraper helper '{name}' is unavailable") from exc


PlanningEntry = _get_scraper_helper("PlanningEntry")
_fetch_arrival_for_course: Callable[[Any], tuple[Sequence[str], str | None, str | None]]
_fetch_arrival_for_course = _get_scraper_helper("fetch_arrival_for_course")


def build_payload(race_id: str) -> dict[str, object]:
    """Fetch arrival information for ``race_id`` and build the API payload."""

    course_id = str(race_id).strip()
    fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    entry = PlanningEntry(rc=course_id, course_id=course_id)

    try:
        numbers, resolved_url, error = _fetch_arrival_for_course(entry)
    except Exception as exc:  # pragma: no cover - network/runtime failure
        payload: dict[str, object] = {
            "race_id": course_id,
            "status": "ERROR",
            "source": "geny",
            "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
            "arrivee": [],
            "error": f"{exc.__class__.__name__}: {exc}",
        }
        return payload

    numbers_list = [str(num) for num in numbers]
    if numbers_list:
        status = "OK"
    elif error in (None, "no-arrival-data"):
        status = "PENDING"
    else:
        status = "ERROR"

    payload = {
        "race_id": course_id,
        "status": status,
        "source": "geny",
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
        "arrivee": numbers_list,
    }
    if resolved_url:
        payload["url"] = resolved_url
    if error and status != "OK":
        payload["error"] = error
    return payload


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and emit the arrival payload."""

    parser = argparse.ArgumentParser(
        description="Fetch the official arrival for a Geny race by course identifier."
    )
    parser.add_argument("--race", required=True, help="Race identifier (e.g. R1C3)")
    args = parser.parse_args(argv)

    payload = build_payload(args.race)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
