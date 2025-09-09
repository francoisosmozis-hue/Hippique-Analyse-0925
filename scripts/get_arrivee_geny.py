#!/usr/bin/env python3
"""Simple utility to generate arrival data from a planning file.

This script acts as a lightweight replacement for the original
``get_arrivee_geny.py`` tool.  It loads a planning JSON file describing
races and writes a results JSON file with a minimal structure.  The
original script scraped official arrivals from external websites; this
version focuses on providing a stable interface for automation while
leaving the fetching logic intentionally minimal.

Usage
-----
python scripts/get_arrivee_gemy.py \
  --planning data/planning/2025-09-25.json \
  --out data/results/2025-09-25_arrivees.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _load_planning(path: Path) -> List[Dict[str, Any]]:
    """Return planning entries from ``path``.

    The planning file is expected to contain a JSON array of objects with at
    least an ``id`` field describing the race identifier.  Entries that do not
    meet this minimal requirement are ignored.
    """

    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh) or []
    if not isinstance(data, list):
        raise ValueError("Planning file must contain a list")
    return [d for d in data if isinstance(d, dict)]


def _fetch_arrival(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return a minimal arrival structure for ``entry``.

    The original project scraped external providers.  In this simplified
    version we merely echo the race identifier with an empty arrival list,
    allowing downstream tooling to proceed without network dependencies.
    """

    race_id = entry.get("id") or f"{entry.get('meeting', '')}{entry.get('race', '')}"
    return {"id": race_id, "arrival": entry.get("arrival", [])}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate arrival data")
    parser.add_argument("--planning", required=True, help="Planning JSON file")
    parser.add_argument("--out", required=True, help="Output JSON file")
    args = parser.parse_args()

    planning = _load_planning(Path(args.planning))
    results = [_fetch_arrival(entry) for entry in planning if entry.get("id") or entry.get("meeting")]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
