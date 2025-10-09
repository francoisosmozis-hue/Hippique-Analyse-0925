#!/usr/bin/env python3
"""
Fetches all individual race URLs for a given historical date from ZEturf.
"""
import argparse
import datetime
import re
import sys
import time
import unicodedata
from typing import List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


def slugify(value: str) -> str:
    """Return a slug suitable for URLs from a human readable string."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("-")


def get_race_urls_for_date(date_str: str) -> List[str]:
    """
    Scrapes Zeturf to find all individual French race URLs for a given date.
    """
    base_url = "https://www.zeturf.fr"
    results_url = f"{base_url}/fr/resultats-et-rapports/{date_str}"
    
    print(f"Fetching meetings page: {results_url}...", file=sys.stderr)
    
    try:
        resp = requests.get(results_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"Error fetching results page: {e}", file=sys.stderr)
        return []

    # Find all links that look like they point to a meeting page for the correct date
    meeting_links = set()
    for link in soup.find_all("a", href=re.compile(f"/fr/reunion/{date_str}/R\\d+-")):
        meeting_links.add(urljoin(base_url, link["href"]))

    race_urls = set()
    for meeting_url in sorted(list(meeting_links)):
        print(f"  -> Fetching courses from meeting: {meeting_url}", file=sys.stderr)
        try:
            resp = requests.get(meeting_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # On the meeting page, find all links to individual courses
            for link in soup.select(f"a[href*='/fr/course/{date_str}/']"):
                race_urls.add(urljoin(base_url, link["href"]))
        except requests.RequestException as e:
            print(f"    Error fetching meeting page: {e}", file=sys.stderr)
            continue
        time.sleep(1) # Be respectful

    return sorted(list(race_urls))


def main():
    parser = argparse.ArgumentParser(description="Fetch historical race URLs from ZEturf.")
    parser.add_argument(
        "date",
        nargs="?",
        help="The date to fetch (YYYY-MM-DD). Defaults to yesterday.",
        default=(datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    )
    args = parser.parse_args()

    urls = get_race_urls_for_date(args.date)
    
    if urls:
        print(f"\nFound {len(urls)} race URLs for {args.date}:", file=sys.stderr)
        for url in urls:
            print(url)
    else:
        print(f"\nNo race URLs found for {args.date}.", file=sys.stderr)


if __name__ == "__main__":
    main()
