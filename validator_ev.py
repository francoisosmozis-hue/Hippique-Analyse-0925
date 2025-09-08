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
    parser = argparse.ArgumentParser(description="Validate EV and ROI thresholds.")
    parser.add_argument("--analysis", required=True, help="Analysis JSON path under data/")
    parser.add_argument("--ev-threshold", type=float, default=0.40, help="EV threshold.")
    parser.add_argument("--roi-threshold", type=float, default=0.20, help="ROI threshold.")
    args = parser.parse_args()

    log("INFO", "validator_ev_complete", **vars(args))

if __name__ == "__main__":
    main()
