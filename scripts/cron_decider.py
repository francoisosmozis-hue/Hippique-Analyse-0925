#!/usr/bin/env python3
"""Decide which race phases to trigger based on planning information.

This script reads a ``meetings.json`` planning file, determines the
current local time in Paris and invokes ``runner_chain.py`` for races
that fall within the H-30 or H-5 windows. ``ALLOW_HEURISTIC`` is forced
to ``0`` for reproducible computations.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.env_utils import get_env

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python <3.9 fallback
    from backports.zoneinfo import ZoneInfo  # type: ignore

PARIS = ZoneInfo("Europe/Paris")

WINDOWS = {
    "H30": (27, 33),
    "H5": (3, 7),
}


def _load_meetings(path: Path) -> Iterable[Dict[str, Any]]:
    """Load meetings data from ``path``.

    The function is tolerant to various JSON shapes and returns an iterable
    of meeting dictionaries.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("meetings") or data.get("reunions") or data.get("data") or []
    else:
        items = data
    return items


def _parse_start(date_hint: str | None, value: str) -> dt.datetime | None:
    """Parse a race start time ``value`` with optional ``date_hint``.

    ``value`` may be an ISO timestamp or a ``HH:MM`` time string.
    Returned datetimes are timezone-aware (Europe/Paris).
    """
    try:
        dtobj = dt.datetime.fromisoformat(value)
    except ValueError:
        if date_hint:
            try:
                dtobj = dt.datetime.fromisoformat(f"{date_hint}T{value}")
            except ValueError:
                return None
        else:
            return None
    if dtobj.tzinfo is None:
        dtobj = dtobj.replace(tzinfo=PARIS)
    return dtobj.astimezone(PARIS)


def _invoke_runner(reunion: str, course: str, phase: str) -> None:
    """Run ``scripts/runner_chain.py`` with the given parameters."""
    cmd = [
        sys.executable,
        "scripts/runner_chain.py",
        "--reunion",
        reunion,
        "--course",
        course,
        "--phase",
        phase,
    ]
    env = os.environ.copy()
    env["ALLOW_HEURISTIC"] = get_env("ALLOW_HEURISTIC", "0")
    subprocess.run(cmd, check=True, env=env)


def main() -> None:
    ap = argparse.ArgumentParser(description="Trigger runner_chain phases based on timing")
    ap.add_argument("--meetings", default="meetings.json", help="Planning JSON file")
    args = ap.parse_args()

    meetings_path = Path(args.meetings)
    if not meetings_path.exists():
        print(f"[WARN] meetings file not found: {meetings_path}")
        return

    now = dt.datetime.now(PARIS)
    meetings = _load_meetings(meetings_path)

    for meeting in meetings:
        r_label = meeting.get("label") or meeting.get("r") or meeting.get("id") or ""
        date_hint = meeting.get("date") or meeting.get("jour")
        courses = meeting.get("courses") or meeting.get("races") or []
        for course in courses:
            c_label = course.get("c") or course.get("course") or course.get("num") or course.get("id") or ""
            start = course.get("start") or course.get("time") or course.get("hour") or course.get("start_time")
            if not r_label or not c_label or not start:
                continue
            dtstart = _parse_start(date_hint, start)
            if not dtstart:
                continue
            delta = (dtstart - now).total_seconds() / 60
            for phase, (mn, mx) in WINDOWS.items():
                if mn <= delta <= mx:
                    _invoke_runner(r_label, c_label, phase)


if __name__ == "__main__":  # pragma: no cover
    main()
