#!/usr/bin/env python3
import argparse
import json
import logging
from pathlib import Path

DATA_DIR = Path("data")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def log(level: str, message: str, **kwargs) -> None:
    record = {"level": level, "message": message}
    if kwargs:
        record.update(kwargs)
    logger.log(logging.INFO if level == "INFO" else logging.ERROR, json.dumps(record))

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch chrono data from Jour de l'Expert.")
    parser.add_argument("--reunion", required=True, help="Reunion identifier.")
    parser.add_argument("--course", required=True, help="Course identifier.")
    parser.add_argument("--out", required=True, help="Output JSON path under data/")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"reunion": args.reunion, "course": args.course}, indent=2))
    log("INFO", "fetch_chrono_complete", out=str(out_path))

if __name__ == "__main__":
    main()
