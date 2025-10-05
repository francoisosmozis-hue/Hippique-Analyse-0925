#!/usr/bin/env python3
"""Fetch today's race schedule and emit a planning JSON file.

The resulting document matches the minimal format expected by tests and
utilities::

    {
      "meetings": [
        {"reunion": "R1", "course": "C1", "time": "2024-01-01T12:00:00"}
      ]
    }

The script relies on the Zeturf meetings endpoint declared in
``config/sources.yml`` and falls back to Geny when necessary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml

from scripts import online_fetch_zeturf as ofz


def _flatten(meetings: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Flatten raw meeting data into ``reunion``/``course``/``time`` records."""
    entries: List[Dict[str, str]] = []
    for meeting in meetings:
        r_label = (
            meeting.get("label")
            or meeting.get("r")
            or meeting.get("id")
            or meeting.get("reunion")
        )
        date = meeting.get("date")
        races = meeting.get("races") or meeting.get("courses") or []
        for race in races:
            c_label = (
                race.get("course") or race.get("c") or race.get("num") or race.get("id")
            )
            time = (
                race.get("time")
                or race.get("start")
                or race.get("hour")
                or race.get("start_time")
            )
            if not (r_label and c_label and time):
                continue
            if date and len(str(time)) == 5 and str(time)[2] == ":":
                time = f"{date}T{time}"
            entries.append(
                {"reunion": str(r_label), "course": str(c_label), "time": str(time)}
            )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch schedule and output meetings.json"
    )
    parser.add_argument(
        "--sources", default="config/sources.yml", help="YAML endpoints file"
    )
    parser.add_argument(
        "--out", default="config/meetings.json", help="Destination JSON path"
    )
    args = parser.parse_args()

    with open(args.sources, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    url = cfg.get("zeturf", {}).get("url")
    if not url:
        raise SystemExit("No Zeturf source URL configured in sources.yml")

    raw = ofz.fetch_meetings(url)
    meetings = ofz.filter_today(raw)
    flat = _flatten(meetings)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"meetings": flat}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
