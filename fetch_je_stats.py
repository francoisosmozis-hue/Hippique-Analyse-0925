"""Lightweight wrapper around :mod:`scripts.fetch_je_stats`.

This module exposes :func:`enrich_from_snapshot` which mirrors the behaviour
expected by the H-5 automation pipeline: starting from a normalised snapshot it
invokes the existing scraping helpers, materialises the ``*_je.csv`` artefact
and returns a structured status dictionary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from analyse_courses_du_jour_enrichie import (
    _extract_id2name,
    _write_je_csv_file,
)
from scripts.fetch_je_stats import collect_stats

StatusDict = dict[str, Any]


def _extract_course_id(snapshot: Mapping[str, Any]) -> str | None:
    """Return the course identifier stored in ``snapshot`` when available."""

    for key in ("course_id", "id_course", "id"):
        value = snapshot.get(key)
        if value not in (None, ""):
            return str(value)

    meta = snapshot.get("meta")
    if isinstance(meta, Mapping):
        return _extract_course_id(meta)

    return None


def enrich_from_snapshot(snapshot_path: str | Path, reunion: str, course: str) -> StatusDict:
    """Fetch jockey/entraineur stats and materialise the JE CSV.

    Parameters
    ----------
    snapshot_path:
        Path to the normalised H-5 snapshot (JSON).
    reunion, course:
        Meeting/course identifiers.  They are currently informative only but
        retained for signature compatibility with the caller.
    """

    del reunion, course  # currently unused but kept for API parity

    snapshot_file = Path(snapshot_path)

    try:
        payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "reason": f"snapshot-error: {exc}"}

    if not isinstance(payload, Mapping):
        return {"ok": False, "reason": "snapshot-invalid"}

    course_id = _extract_course_id(payload)
    if not course_id:
        return {"ok": False, "reason": "missing-course-id"}

    try:
        coverage, mapped = collect_stats(course_id, h5_path=str(snapshot_file))
    except Exception as exc:  # network/HTTP errors bubble up here
        return {"ok": False, "reason": str(exc)}

    stats_payload: dict[str, Any] = {"coverage": coverage}
    stats_payload.update(mapped)

    course_dir = snapshot_file.parent
    stats_path = course_dir / "stats_je.json"
    je_csv_path = course_dir / f"{snapshot_file.stem}_je.csv"

    try:
        course_dir.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(
            json.dumps(stats_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        id2name = _extract_id2name(payload)
        if not id2name:
            id2name = {cid: "" for cid in mapped.keys()}
        _write_je_csv_file(
            je_csv_path,
            id2name=id2name,
            stats_payload=stats_payload,
        )
    except Exception as exc:
        return {"ok": False, "reason": f"io-error: {exc}"}

    return {
        "ok": True,
        "coverage": coverage,
        "paths": {
            "stats_json": str(stats_path),
            "je_csv": str(je_csv_path),
        },
    }


__all__ = ["enrich_from_snapshot"]
