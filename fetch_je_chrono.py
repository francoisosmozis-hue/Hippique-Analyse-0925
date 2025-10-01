"""Helpers to materialise chronos artefacts from stored snapshots."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from analyse_courses_du_jour_enrichie import _write_chronos_csv, _write_minimal_csv

LOGGER = logging.getLogger(__name__)


def _load_json(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _iter_runners(snapshot: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
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


def _discover_payload(snapshot_dir: Path) -> Mapping[str, Any]:
    candidates = [snapshot_dir / "partants.json", snapshot_dir / "normalized_h5.json"]
    candidates.extend(sorted(snapshot_dir.glob("*_H-5.json"), reverse=True))

    for candidate in candidates:
        payload = _load_json(candidate)
        if payload:
            return payload

    raise RuntimeError("snapshot-missing")


def _materialise_chronos(snapshot_dir: Path, reunion: str, course: str) -> Path:
    payload = _discover_payload(snapshot_dir)
    runners = list(_iter_runners(payload))
    chronos_path = snapshot_dir / f"{reunion}{course}_chronos.csv"
    try:
        _write_chronos_csv(chronos_path, runners)
    except Exception:  # pragma: no cover - defensive
        LOGGER.exception(
            "Failed to materialise chronos CSV for %s%s in %s", reunion, course, snapshot_dir
        )
        placeholder_headers = ["num", "chrono", "ok"]
        placeholder_rows = [["", "", 0]]
        _write_minimal_csv(chronos_path, placeholder_headers, placeholder_rows)

    legacy_path = snapshot_dir / "chronos.csv"
    if legacy_path != chronos_path:
        try:
            _write_chronos_csv(legacy_path, runners)
        except Exception:  # pragma: no cover - defensive
            LOGGER.exception("Failed to materialise legacy chronos CSV in %s", snapshot_dir)
            placeholder_headers = ["num", "chrono", "ok"]
            placeholder_rows = [["", "", 0]]
            _write_minimal_csv(legacy_path, placeholder_headers, placeholder_rows)

    return chronos_path
    
    
def enrich_from_snapshot(snapshot_dir: str | Path, reunion: str, course: str) -> Path:
    """Spawn the CLI helper to generate chronos artefacts for ``snapshot_dir``."""

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
            "fetch_je_chrono CLI failed for %s%s (returncode=%s)",
            reunion_code,
            course_code,
            result.returncode,
        )
    return out_dir / f"{reunion_code}{course_code}_chronos.csv"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build chronos artefacts")
    parser.add_argument("--out", required=True, help="Répertoire destination")
    parser.add_argument("--reunion", required=True, help="Identifiant réunion (ex: R1)")
    parser.add_argument("--course", required=True, help="Identifiant course (ex: C1)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    snapshot_dir = Path(args.out)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    try:
        _materialise_chronos(snapshot_dir, args.reunion.upper(), args.course.upper())
    except RuntimeError as exc:
        print(f"[ERROR] fetch_je_chrono: {exc}", file=sys.stderr)
        return 1

    return 0

    
if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = ["enrich_from_snapshot"]
