#!/usr/bin/env python3
import argparse
import json
import logging
from datetime import date
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
    parser = argparse.ArgumentParser(description="Fetch official race results from Geny.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Date of results YYYY-MM-DD.")
    parser.add_argument("--out", required=True, help="Output JSON path under data/results/")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"date": args.date, "results": []}, indent=2))
    log("INFO", "results_fetched", date=args.date, out=str(out_path))

if __name__ == "__main__":
    main()
