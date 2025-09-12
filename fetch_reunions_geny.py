#!/usr/bin/env python3
"""Fetch PMU reunions from Geny and build ZEturf URLs."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

GENY_URL = "https://www.geny.com/reunions-courses-pmu/_daujourdhui"


def _slugify(value: str) -> str:
    """Return a slug suitable for URLs from a human readable string."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("-")


def _fetch_reunions() -> List[Dict[str, str]]:
    """Download Geny page and extract reunion data."""
    resp = requests.get(GENY_URL, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    reunions: List[Dict[str, str]] = []
    for section in soup.select("section.reunion"):
        title_el = section.select_one("h2")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        match = re.search(r"R\d+", title)
        if not match:
            continue
        label = match.group(0)
        hippo = title[match.end():].strip(" -")
        hippo = re.sub(r"\s*\([A-Z]{2}\)$", "", hippo)

        # Extract Geny link even if not used later
        link_el = section.select_one("h2 a")
        geny_link = link_el.get("href", "") if link_el else ""
        _ = geny_link  # satisfy extraction requirement

        reunions.append({"label": label, "hippodrome": hippo})

    return reunions


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Geny reunions list.")
    parser.add_argument(
        "--date",
        default=date.today().strftime("%Y-%m-%d"),
        help="Date to use in the output JSON (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument("--out", required=True, help="Path to output JSON file")
    args = parser.parse_args()

    reunions = _fetch_reunions()
    data = {"date": args.date, "reunions": []}
    for reunion in reunions:
        slug = _slugify(reunion["hippodrome"])
        url_zeturf = f"https://www.zeturf.fr/fr/reunion/{args.date}/{reunion['label']}-{slug}"
        data["reunions"].append(
            {
                "label": reunion["label"],
                "hippodrome": reunion["hippodrome"],
                "url_zeturf": url_zeturf,
            }
        )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":  # pragma: no cover
    main()
