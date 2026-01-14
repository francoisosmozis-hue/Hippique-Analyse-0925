import json
import sys
import asyncio
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hippique_orchestrator.scrapers.boturfers import BoturfersFetcher


async def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_boturfers_snapshot_scraper.py <html_file> <race_url>")
        sys.exit(1)

    html_file_path = sys.argv[1]
    race_url = sys.argv[2]

    with open(html_file_path, encoding='utf-8') as f:
        html_content = f.read()

    # Create a BoturfersFetcher instance
    # We will manually set the soup since we're providing an HTML file
    fetcher = BoturfersFetcher(race_url=race_url)
    fetcher.soup = BeautifulSoup(html_content, "lxml") # Use lxml for consistency

    snapshot = await fetcher.get_race_snapshot()

    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    if snapshot and snapshot.get("runners"):
        print(f"SUCCESS: Scraped {len(snapshot['runners'])} runners.")
    else:
        print("FAILURE: No snapshot data or runners found.")

if __name__ == "__main__":
    asyncio.run(main())
