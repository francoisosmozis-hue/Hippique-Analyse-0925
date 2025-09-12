#!/usr/bin/env python3
"""Fetch today's race meetings from Zeturf and save to JSON."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from typing import Any, Dict, List

import requests
import yaml
from bs4 import BeautifulSoup

import online_fetch_zeturf as core

GENY_FALLBACK_URL = "https://www.geny.com/reunions-courses-pmu"


def _fetch_from_geny() -> Dict[str, Any]:
    """Scrape meetings from Geny when the Zeturf API is unavailable."""
    resp = requests.get(GENY_FALLBACK_URL, timeout=10)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    today = dt.date.today().isoformat()
    meetings: List[Dict[str, Any]] = []
    for li in soup.select("li[data-date]"):
        date = li["data-date"]
        if date != today:
            continue
        meetings.append(
            {
                "id": li.get("data-id"),
                "name": li.get_text(strip=True),
                "date": date,
            }
        )
    return {"meetings": meetings}


@@ -43,49 +45,66 @@ def fetch_meetings(url: str) -> Any:
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.Timeout:
        return _fetch_from_geny()
    except requests.HTTPError as exc:  # pragma: no cover - exercised via test
        status = exc.response.status_code if exc.response is not None else None
        if status == 404:
            return _fetch_from_geny()
            
        raise


def filter_today(meetings: Any) -> List[Dict[str, Any]]:
    """Filter meetings that occur today based on a ``date`` field."""
    today = dt.date.today().isoformat()
    items = meetings
    if isinstance(meetings, dict):
        items = meetings.get("meetings") or meetings.get("data") or []
    return [m for m in items if m.get("date") == today]


def main() -> None:    
    parser.add_argument("--out", required=True, help="Output JSON file")
    parser.add_argument("--out", help="Output JSON file")
    parser.add_argument(
        "--sources", default="config/sources.yml", help="Path to sources YAML config"
    )    
    parser.add_argument(
        "--mode", default="planning", help="Operational mode (planning or diff)"
    )
    parser.add_argument("--course-id", help="Course identifier when mode=diff")
    parser.add_argument("--h30", help="Path to H-30 snapshot (mode=diff)")
    parser.add_argument("--h5", help="Path to H-5 snapshot (mode=diff)")
    parser.add_argument(
        "--outdir", default="snapshots", help="Directory for diff output (mode=diff)"
    )
    args = parser.parse_args()

    if args.mode == "diff":
        if not (args.course_id and args.h30 and args.h5):
            parser.error("--course-id, --h30 and --h5 are required in diff mode")
        core.make_diff(args.course_id, args.h30, args.h5, outdir=args.outdir)
        return

    if not args.out:
        parser.error("--out is required in planning mode")

    with open(args.sources, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}

    url = config.get("zeturf", {}).get("url")
    if not url:
        raise ValueError("No Zeturf source URL configured in sources.yml")

    meetings = fetch_meetings(url)
    today_meetings = filter_today(meetings)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(today_meetings, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
