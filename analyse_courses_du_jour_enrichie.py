#!/usr/bin/env python3
"""Pipeline helper for analysing today's horse races.

This script optionally discovers all French meetings of the day from Geny and
runs a small pipeline on each course. The behaviour without the ``--from-geny-today``
flag is intentionally minimal in order to preserve the previous behaviour (if
any) of the script.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency in tests
    from scripts.online_fetch_zeturf import write_snapshot_from_geny
except Exception:  # pragma: no cover - used when optional deps are missing
    def write_snapshot_from_geny(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("write_snapshot_from_geny is unavailable")


# ---------------------------------------------------------------------------
# Helper stubs - these functions are expected to be provided elsewhere in the
# larger project. They are defined here so the module can be imported and easily
# monkeypatched during tests.
# ---------------------------------------------------------------------------


def ensure_dir(path: Path) -> Path:
    """Create ``path`` if it does not exist and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def enrich_h5(rc_dir: Path, *, budget: float, kelly: float) -> None:  # pragma: no cover - stub
    return None


def build_p_finale(rc_dir: Path, *, budget: float, kelly: float) -> None:  # pragma: no cover - stub
    return None


def run_pipeline(rc_dir: Path, *, budget: float, kelly: float) -> None:  # pragma: no cover - stub
    return None


def build_prompt_from_meta(rc_dir: Path, *, budget: float, kelly: float) -> None:  # pragma: no cover - stub
    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyse courses du jour enrichie")
    ap.add_argument("--data-dir", default="data", help="Répertoire racine pour les sorties")
    ap.add_argument("--budget", type=float, default=100.0, help="Budget à utiliser")
    ap.add_argument("--kelly", type=float, default=1.0, help="Fraction de Kelly à appliquer")
    ap.add_argument(
        "--from-geny-today",
        action="store_true",
        help="Découvre toutes les réunions FR du jour via Geny et traite H30/H5",
    )
    args = ap.parse_args()

    if args.from_geny_today:
        raw = subprocess.check_output([sys.executable, "discover_geny_today.py"], text=True)
        payload = json.loads(raw)
        meetings = payload.get("meetings", [])
        base_dir = ensure_dir(Path(args.data_dir))
        for meeting in meetings:
            r_label = meeting.get("r", "")
            for course in meeting.get("courses", []):
                c_label = course.get("c", "")
                rc_dir = ensure_dir(base_dir / f"{r_label}{c_label}")
                course_id = course.get("id_course")
                if not course_id:
                    continue
                write_snapshot_from_geny(course_id, "H30", rc_dir)
                write_snapshot_from_geny(course_id, "H5", rc_dir)
                enrich_h5(rc_dir, budget=args.budget, kelly=args.kelly)
                build_p_finale(rc_dir, budget=args.budget, kelly=args.kelly)
                run_pipeline(rc_dir, budget=args.budget, kelly=args.kelly)
                build_prompt_from_meta(rc_dir, budget=args.budget, kelly=args.kelly)
        print("[DONE] from-geny-today pipeline terminé.")
        return

    # Fall back to original behaviour: simply run the pipeline on ``data_dir``
    run_pipeline(Path(args.data_dir), budget=args.budget, kelly=args.kelly)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
