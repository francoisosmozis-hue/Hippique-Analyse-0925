#!/usr/bin/env python3
"""Run scheduled H-30 and H-5 windows based on a planning file.

This lightweight runner loads the day's planning and for each race determines
whether the start time falls within the configured H-30 or H-5 windows.  When a
window matches, snapshot/analysis files are written under the designated
directories.  The analysis step now leverages :func:`simulate_ev_batch` and
``validate_ev`` to compute and validate EV/ROI metrics.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulate_ev import simulate_ev_batch
from validator_ev import ValidationError, validate_ev

logger = logging.getLogger(__name__)

USE_DRIVE = os.getenv("USE_DRIVE", "false").lower() == "true"
if USE_DRIVE:
    try:
        from scripts.drive_sync import upload_file
    except Exception as exc:  # pragma: no cover - optional dependency guards
        logger.warning("Drive sync unavailable, disabling uploads: %s", exc)
        upload_file = None  # type: ignore[assignment]
        USE_DRIVE = False
else:  # pragma: no cover - simple fallback when Drive is disabled
    upload_file = None  # type: ignore[assignment]

def _load_planning(path: Path) -> List[Dict[str, Any]]:
    """Return planning entries from ``path``.

    The planning file is expected to be a JSON array of objects containing at
    least ``id`` and ``start`` (ISO timestamp) fields.  Entries missing these
    fields are ignored.
    """
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh) or []
    if not isinstance(data, list):
        raise ValueError("Planning file must contain a list")
    return [d for d in data if isinstance(d, dict)]


def _write_snapshot(race_id: str, window: str, base: Path) -> None:
    """Write a snapshot file for ``race_id`` under ``base``.

    Parameters
    ----------
    race_id:
        Identifier for the race, e.g. ``"R1C3"``.
    window:
        Window label (``"H30"`` or ``"H5"``).
    base:
        Base directory where snapshot files are written.
    """
    dest = base / race_id
    dest.mkdir(parents=True, exist_ok=True)
    payload = {
        "race_id": race_id,
        "window": window,
        "timestamp": dt.datetime.now().isoformat(),
    }
    path = dest / f"snapshot_{window}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    if USE_DRIVE and upload_file:
        try:
            upload_file(path)
        except EnvironmentError as exc:
            logger.warning("Skipping Drive upload for %s: %s", path, exc)
    else:
        logger.info("[drive] Skipping upload for %s (USE_DRIVE disabled)", path)


def _write_analysis(
    race_id: str,
    base: Path,
    *,
    budget: float,
    ev_min: float,
    roi_min: float,
    mode: str,
) -> None:
    """Compute a dummy EV/ROI analysis and write it to disk."""
    dest = base / race_id
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[runner] Mode={mode} RC={race_id} → {dest}")

    tickets = [{"p": 0.5, "odds": 2.0, "stake": 1.0}]
    stats = simulate_ev_batch(tickets, bankroll=budget)
    try:
        validate_ev(float(stats.get("ev", 0.0)), None, need_combo=False)
    except ValidationError:
        return
    payload = {
        "race_id": race_id,
        "ev": stats.get("ev"),
        "roi": stats.get("roi"),
        "green": stats.get("green"),
    }
    path = dest / "analysis.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    if USE_DRIVE and upload_file:
        try:
            upload_file(path)
        except EnvironmentError as exc:
            logger.warning("Skipping Drive upload for %s: %s", path, exc)
    else:
        logger.info("[drive] Skipping upload for %s (USE_DRIVE disabled)", path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run H-30 and H-5 windows from planning information"
    )
    parser.add_argument("--planning", required=True, help="Path to planning JSON file")
    parser.add_argument("--h30-window-min", type=int, default=27)
    parser.add_argument("--h30-window-max", type=int, default=33)
    parser.add_argument("--h5-window-min", type=int, default=3)
    parser.add_argument("--h5-window-max", type=int, default=7)
    parser.add_argument("--snap-dir", default="data/snapshots")
    parser.add_argument("--analysis-dir", default="data/analyses")
    parser.add_argument("--budget", type=float, default=5.0)
    parser.add_argument("--ev-min", type=float, default=0.35)
    parser.add_argument("--roi-min", type=float, default=0.25)
    parser.add_argument("--pastille-rule", default="", help="Unused placeholder")
    parser.add_argument("--gpi-config", default="", help="Path to GPI config (unused)")
    parser.add_argument(
        "--payout-calib", default="", help="Path to payout calibration (unused)"
    )
    parser.add_argument("--mode", default="hminus5", help="Mode de traitement (log only)")
    parser.add_argument(
        "--output",
        default=None,
        help="Répertoire de sortie prioritaire (fallback vers $OUTPUT_DIR puis --analysis-dir)",
    )
    args = parser.parse_args()

    planning = _load_planning(Path(args.planning))
    now = dt.datetime.now()

    snap_dir = Path(args.snap_dir)
    analysis_root = args.output or os.getenv("OUTPUT_DIR") or args.analysis_dir
    analysis_dir = Path(analysis_root)

    for entry in planning:
        race_id = entry.get("id") or f"{entry.get('meeting', '')}{entry.get('race', '')}"
        start = entry.get("start")
        if not race_id or not start:
            continue
        try:
            start_time = dt.datetime.fromisoformat(start)
        except ValueError:
            continue
        delta = (start_time - now).total_seconds() / 60
        if args.h30_window_min <= delta <= args.h30_window_max:
            _write_snapshot(race_id, "H30", snap_dir)
        if args.h5_window_min <= delta <= args.h5_window_max:
            _write_snapshot(race_id, "H5", snap_dir)
            _write_analysis(
                race_id,
                analysis_dir,
                budget=args.budget,
                ev_min=args.ev_min,
                roi_min=args.roi_min,
                mode=args.mode,
            )


if __name__ == "__main__":
    main()
