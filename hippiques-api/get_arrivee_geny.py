#!/usr/bin/env python3
"""Minimal CLI stub for fetching Geny race arrivals.

This script offers the same CLI surface as the future scraper so that the
API can already pipe results through ``subprocess``.  It only accepts the
``--race`` argument and prints a JSON document describing a fake arrival.
Replace the "FAKE DATA" section with the real scraping logic when ready.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys


def build_stub_payload(race_id: str) -> dict[str, object]:
    """Return a deterministic JSON payload for the given ``race_id``."""

fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    return {
        "race_id": race_id,
        "status": "OK",
        "source": "geny",
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
        "arrivee": ["7", "3", "1", "6", "5"],  # stub values, replace later
    }


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and emit the stub arrival payload."""

    parser = argparse.ArgumentParser(
        description=(
            "Stub Geny arrival fetcher. Replace the fake data with real "
            "scraping when it becomes available."
        )
    )
    parser.add_argument("--race", required=True, help="Race identifier (e.g. R1C3)")
    args = parser.parse_args(argv)

    payload = build_stub_payload(args.race)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
