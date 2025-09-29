"""Chronos enrichment helper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from analyse_courses_du_jour_enrichie import _write_chronos_csv


def _iter_runners(snapshot: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    """Yield runner dictionaries from the snapshot payload."""

    runners = snapshot.get("runners")
    if isinstance(runners, list):
        for runner in runners:
            if isinstance(runner, Mapping):
                yield runner

    partants = snapshot.get("partants")
    if isinstance(partants, Mapping):
        runners = partants.get("runners")
        if isinstance(runners, list):
            for runner in runners:
                if isinstance(runner, Mapping):
                    yield runner


def enrich_from_snapshot(snapshot_path: str | Path, reunion: str, course: str) -> dict[str, Any]:
    """Materialise ``chronos.csv`` based on the provided snapshot."""

    del reunion, course  # signature parity

    snapshot_file = Path(snapshot_path)
    try:
        payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "reason": f"snapshot-error: {exc}"}

    if not isinstance(payload, Mapping):
        return {"ok": False, "reason": "snapshot-invalid"}

    course_dir = snapshot_file.parent
    chronos_path = course_dir / "chronos.csv"

    try:
        course_dir.mkdir(parents=True, exist_ok=True)
        _write_chronos_csv(chronos_path, _iter_runners(payload))
    except Exception as exc:
        return {"ok": False, "reason": f"io-error: {exc}"}

    return {"ok": True, "paths": {"chronos": str(chronos_path)}}


__all__ = ["enrich_from_snapshot"]
