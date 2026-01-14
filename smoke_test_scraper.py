"""
smoke_test_scraper.py

A utility script to perform a live smoke test of the scraping process for a given race URL.
This script bypasses all mocks and makes real network calls.

Usage:
    python smoke_test_scraper.py <race_url>
"""

import asyncio
import json
import sys

from hippique_orchestrator.source_registry import source_registry
from hippique_orchestrator.logging_utils import get_logger

# Configure a basic logger for this script
logger = get_logger(__name__)


async def main(race_url: str):
    """
    Asynchronously calls the source_registry to get a snapshot and prints the result.
    """
    logger.info(f"Starting smoke test for URL: {race_url}")

    # This will trigger the full primary -> fallback -> enrichment logic
    snapshot = await source_registry.get_snapshot(race_url)

    if not snapshot:
        logger.error("Failed to retrieve any snapshot for the given URL.")
        return

    # Convert the Pydantic model to a dictionary and print as JSON
    snapshot_dict = snapshot.model_dump(mode="json")
    print(json.dumps(snapshot_dict, indent=2, ensure_ascii=False))

    logger.info("Smoke test finished.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python smoke_test_scraper.py <race_url>")
        sys.exit(1)

    url_to_test = sys.argv[1]
    asyncio.run(main(url_to_test))
