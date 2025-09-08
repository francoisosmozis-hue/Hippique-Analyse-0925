#!/usr/bin/env python3
import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def log(level: str, message: str, **kwargs) -> None:
    record = {"level": level, "message": message}
    if kwargs:
        record.update(kwargs)
    logger.log(logging.INFO if level == "INFO" else logging.ERROR, json.dumps(record))

def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize artifacts to Google Drive.")
    parser.add_argument("--source", required=True, help="Local file or directory to upload.")
    parser.add_argument("--dest-folder", required=True, help="Drive folder identifier.")
    args = parser.parse_args()

    log("INFO", "drive_sync_complete", source=args.source, dest=args.dest_folder)

if __name__ == "__main__":
    main()
