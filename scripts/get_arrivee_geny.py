#!/usr/bin/env python3
"""Retrieve race results from Geny and store them as JSON.

This is a minimal implementation intended to make the post-results
workflow functional.  It downloads the public results page from Geny,
extracts course headings and writes the data to
``data/results/ARRIVEES.json``.  If the remote service is unavailable,
we simply write an empty structure so the workflow can continue.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.geny.com/resultats"


def fetch_results(date: str) -> List[Dict[str, str]]:
    """Fetch race result headings from Geny for a given date.

    Parameters
    ----------
    date:
        Date string in ``YYYY-MM-DD`` format.
    """
    url = f"{BASE_URL}?date={date}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results: List[Dict[str, str]] = []
    for course in soup.select("div.course"):
        heading = course.find("h2")
        if heading:
            results.append({"course": heading.get_text(strip=True)})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch race results from Geny")
    parser.add_argument(
        "--out",
        default="data/results/ARRIVEES.json",
        help="Output JSON file",
    )
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Date in YYYY-MM-DD format",
    )
    args = parser.parse_args()

    data = {
        "date": args.date,
        "results": fetch_results(args.date),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
