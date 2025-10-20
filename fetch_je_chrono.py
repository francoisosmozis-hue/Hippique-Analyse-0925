"""Helpers to materialise chronos artefacts from a snapshot."""

from __future__ import annotations
import argparse
import logging
from pathlib import Path
import sys

# Add project root to path to allow imports from scripts
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scripts.snapshot_enricher import enrich_from_snapshot
except ImportError:
    print(
        "ERROR: Could not import enrich_from_snapshot. Make sure scripts/snapshot_enricher.py exists.",
        file=sys.stderr,
    )
    sys.exit(1)

LOGGER = logging.getLogger(__name__)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate chronos.csv and je_stats.csv from a snapshot."
    )
    parser.add_argument("snapshot_path", help="Path to the JSON snapshot file.")
    parser.add_argument("out_dir", help="Directory to write the CSV files to.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    results = enrich_from_snapshot(args.snapshot_path, args.out_dir)
    if results.get("chronos"):
        LOGGER.info("Successfully created chronos file: %s", results["chronos"])
    if results.get("je_stats"):
        LOGGER.info("Successfully created je_stats file: %s", results["je_stats"])


if __name__ == "__main__":
    main()
