"""Helpers to materialise jockey/entraineur statistics."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from analyse_courses_du_jour_enrichie import (
    _extract_id2name,
    _write_je_csv_file,
    _write_json_file,
    _write_minimal_csv,
)
from scripts.fetch_je_stats import collect_stats


LOGGER = logging.getLogger(__name__)


def _load_json(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _iter_snapshot_candidates(snapshot_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    normalized = snapshot_dir / "normalized_h5.json"
    if normalized.exists():
        candidates.append(normalized)
    candidates.extend(sorted(snapshot_dir.glob("*_H-5.json"), reverse=True))
    return candidates


def _extract_course_id(snapshot: Mapping[str, Any]) -> str | None:
    for key in ("course_id", "id_course", "id"):
        value = snapshot.get(key)
        if value not in (None, ""):
            return str(value)

    meta = snapshot.get("meta")
    if isinstance(meta, Mapping):
        return _extract_course_id(meta)

    return None


def _discover_snapshot(snapshot_dir: Path) -> tuple[Path, Mapping[str, Any]]:
    for candidate in _iter_snapshot_candidates(snapshot_dir):
        payload = _load_json(candidate)
        if payload:
            return candidate, payload
    raise RuntimeError("snapshot-missing")

    
def _extract_id_mapping(snapshot_dir: Path, payload: Mapping[str, Any]) -> Mapping[str, str]:
    mapping = _extract_id2name(payload)
    if mapping:
        return mapping

    fallback = snapshot_dir / "partants.json"
    other_payload = _load_json(fallback)
    if other_payload:
        mapping = _extract_id2name(other_payload)
    return mapping or {}

    
def _materialise_stats(snapshot_dir: Path, reunion: str, course: str) -> Path:
    snapshot_file, payload = _discover_snapshot(snapshot_dir)

    course_id = _extract_course_id(payload)
    if not course_id:
        raise RuntimeError("missing-course-id")

    stats_path = snapshot_dir / "stats_je.json"
    csv_path = snapshot_dir / f"{reunion}{course}_je.csv"
    legacy_csv_path = snapshot_dir / f"{snapshot_file.stem}_je.csv"
    
    try:
        coverage, mapped = collect_stats(course_id, h5_path=str(snapshot_file))
    except Exception:  # pragma: no cover - network or scraping issues
        LOGGER.exception("collect_stats failed for course %s", course_id)
        stats_payload = {"coverage": 0, "ok": 0}
        _write_json_file(stats_path, stats_payload)
        placeholder_headers = ["num", "nom", "j_rate", "e_rate", "ok"]
        placeholder_rows = [["", "", "", "", 0]]
        _write_minimal_csv(csv_path, placeholder_headers, placeholder_rows)
        if legacy_csv_path != csv_path:
            _write_minimal_csv(legacy_csv_path, placeholder_headers, placeholder_rows)
        return csv_path
        
    stats_payload: dict[str, Any] = {"coverage": coverage}
    stats_payload.update(mapped)

    _write_json_file(stats_path, stats_payload)

    id2name = _extract_id_mapping(snapshot_dir, payload)
    if not id2name:
        id2name = {cid: "" for cid in mapped.keys()}

    _write_je_csv_file(
        csv_path,
        id2name=id2name,
        stats_payload=stats_payload,
    )

    if legacy_csv_path != csv_path:
        _write_je_csv_file(
            legacy_csv_path,
            id2name=id2name,
            stats_payload=stats_payload,
        )
    
    return csv_path


def enrich_from_snapshot(snapshot_dir: str | Path, reunion: str, course: str) -> Path:
    """Spawn the CLI helper to generate J/E statistics for ``snapshot_dir``."""

    out_dir = Path(snapshot_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    reunion_code = reunion.upper()
    course_code = course.upper()

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--out",
        str(out_dir),
        "--reunion",
        reunion_code,
        "--course",
        course_code,
    ]

    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        LOGGER.warning(
            "fetch_je_stats CLI failed for %s%s (returncode=%s)",
            reunion_code,
            course_code,
            result.returncode,
        )
    return out_dir / f"{reunion_code}{course_code}_je.csv"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build JE statistics artefacts")
    parser.add_argument("--out", required=True, help="Répertoire destination")
    parser.add_argument("--reunion", required=True, help="Identifiant réunion (ex: R1)")
    parser.add_argument("--course", required=True, help="Identifiant course (ex: C1)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    snapshot_dir = Path(args.out)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    try:
        _materialise_stats(snapshot_dir, args.reunion.upper(), args.course.upper())
    except RuntimeError as exc:
        print(f"[ERROR] fetch_je_stats: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = ["enrich_from_snapshot"]
