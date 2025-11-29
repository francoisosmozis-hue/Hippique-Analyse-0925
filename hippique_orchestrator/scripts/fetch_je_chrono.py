"""Helpers to materialise chronos artefacts from a snapshot."""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, TypeAlias

LOGGER = logging.getLogger(__name__)

ResultDict: TypeAlias = dict[str, str | None]


def enrich_from_snapshot(snapshot_path: str, out_dir: str) -> dict:
    """Build ``je_stats.csv`` and ``chronos.csv`` files from ``snapshot_path``.

    Parameters
    ----------
    snapshot_path:
        Path to the JSON snapshot describing the runners.
    out_dir:
        Directory where the CSV files will be written.

    Returns
    -------
    dict
        Mapping with the keys ``"je_stats"`` and ``"chronos"`` whose values are the
        paths to the generated files (as strings) or ``None`` when the artefact
        could not be produced.
    """

    result: ResultDict = {"je_stats": None, "chronos": None}

    snapshot_file = Path(snapshot_path)
    try:
        raw_payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        LOGGER.warning("Snapshot %s does not exist", snapshot_file)
        return result
    except (OSError, json.JSONDecodeError):
        LOGGER.exception("Unable to load snapshot %s", snapshot_file)
        return result

    if not isinstance(raw_payload, Mapping):
        LOGGER.warning("Snapshot %s is not a JSON object", snapshot_file)
        payload: Mapping[str, Any] = {}
    else:
        payload = raw_payload

    runners_field = payload.get("runners")
    runners: list[Mapping[str, Any]] = []
    if isinstance(runners_field, list):
        for index, runner in enumerate(runners_field):
            if isinstance(runner, Mapping):
                runners.append(runner)
            else:
                LOGGER.warning(
                    "Runner entry %s in %s is not an object and will be ignored",
                    index,
                    snapshot_file,
                )
    else:
        LOGGER.warning("Snapshot %s is missing a 'runners' array", snapshot_file)

    normalised = list(_normalise_runners(runners, snapshot_file))

    output_dir = Path(out_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        LOGGER.exception("Unable to create output directory %s", output_dir)
        return result

    je_path = output_dir / "je_stats.csv"
    chronos_path = output_dir / "chronos.csv"

    try:
        _write_csv(je_path, normalised, ("num", "nom", "j_rate", "e_rate"))
    except OSError:
        LOGGER.exception("Failed to write JE statistics CSV at %s", je_path)
    else:
        result["je_stats"] = str(je_path)

    try:
        _write_csv(chronos_path, normalised, ("num", "chrono"))
    except OSError:
        LOGGER.exception("Failed to write chronos CSV at %s", chronos_path)
    else:
        result["chronos"] = str(chronos_path)

    return result


def _normalise_runners(
    runners: Iterable[Mapping[str, Any]], snapshot_file: Path
) -> Iterable[dict[str, str]]:
    for index, runner in enumerate(runners):
        descriptor = _runner_descriptor(runner, index)
        num = _extract_value(
            runner,
            ("num", "number", "id"),
            snapshot_file,
            descriptor,
            "num",
        )
        yield {
            "num": num,
            "nom": _extract_value(
                runner,
                ("nom", "name", "horse", "label"),
                snapshot_file,
                descriptor,
                "nom",
            ),
            "j_rate": _extract_value(
                runner,
                ("j_rate", "j_win", "jockey_rate"),
                snapshot_file,
                descriptor,
                "j_rate",
            ),
            "e_rate": _extract_value(
                runner,
                ("e_rate", "e_win", "trainer_rate"),
                snapshot_file,
                descriptor,
                "e_rate",
            ),
            "chrono": _extract_value(
                runner,
                ("chrono", "time"),
                snapshot_file,
                descriptor,
                "chrono",
            ),
        }


def _runner_descriptor(runner: Mapping[str, Any], index: int) -> str:
    for key in ("num", "number", "id"):
        value = runner.get(key)
        if value not in (None, ""):
            return f"{key}={value}"
    return f"index {index}"


def _extract_value(
    runner: Mapping[str, Any],
    keys: Iterable[str],
    snapshot_file: Path,
    descriptor: str,
    label: str,
) -> str:
    for key in keys:
        value = runner.get(key)
        if value not in (None, ""):
            return str(value)

    LOGGER.warning(
        "Runner %s in %s is missing '%s'; using empty string",
        descriptor,
        snapshot_file,
        label,
    )
    return ""


def _write_csv(path: Path, rows: Iterable[dict[str, str]], columns: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = list(columns)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(column, "") for column in header])

__all__ = ["enrich_from_snapshot"]
