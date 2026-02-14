#!/usr/bin/env python
# scripts/smoke_live.py
import os
import sys
import logging
from datetime import date
from typing import List # Added for List type hint

from hippique_orchestrator.analysis_pipeline import run_analysis_for_race
from hippique_orchestrator.providers.base import Provider
from hippique_orchestrator.providers.aggregate import AggregateProvider
from hippique_orchestrator.providers.boturfers_provider import BoturfersProvider
from tests.providers.file_based_provider import FileBasedProvider

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

# --- Guardrails ---
if os.getenv('CI'):
    print("CI environment detected. Skipping live smoke test.")
    sys.exit(0)

if not os.getenv('LIVE'):
    print("LIVE environment variable not set. Set LIVE=1 to run.")
    sys.exit(0)

# --- Config ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TARGET_DATE = date.fromisoformat(os.getenv('DATE', date.today().isoformat()))
PROVIDER_NAME = os.getenv('PROVIDER', 'file').lower() # Default to file for safety
N_RACES = int(os.getenv('N_RACES', '3'))
DUMMY_GPI_CONFIG = {"budget": 100, "roi_min_global": 0.05}

# --- Provider Factory ---
def get_providers(name: str) -> List[Provider]:
    if name == 'boturfers':
        return [BoturfersProvider()]
    else:
        raise ValueError(f"Unknown provider: {name}")

# --- Main ---
def main():
    logging.info(f"--- Smoke Test ---")
    logging.info(f"Date: {TARGET_DATE}, Provider: {PROVIDER_NAME}, Max Races: {N_RACES}")

    try:
        providers = get_providers(PROVIDER_NAME)
        agg_provider = AggregateProvider(providers)
        programme = agg_provider.fetch_programme(for_date=TARGET_DATE)
    except Exception as e:
        logging.exception(f"Failed to fetch programme: {e}")
        sys.exit(1)

    # --- Assertions ---
    failures = 0
    if len(programme) == 0:
        logging.error("FAIL: No races detected in the programme.")
        failures += 1
    else:
        logging.info(f"PASS: Detected {len(programme)} races.")

    for race in programme[:N_RACES]:
        logging.info(f"--- Analyzing race_uid: {race.race_uid[:12]}... ---")
        try:
            result = run_analysis_for_race(race, agg_provider, DUMMY_GPI_CONFIG)

            if not result.race_uid:
                logging.error("FAIL: race_uid is empty.")
                failures += 1

            if not result.playable and not result.abstention_reasons:
                logging.error("FAIL: Abstention without explicit reason.")
                failures += 1
            elif not result.playable:
                logging.info(f"PASS: Abstention correctly reported: {result.abstention_reasons}")

            if 'drift_not_calculable' in result.quality_report.reasons:
                 logging.info(f"PASS: Missing drift correctly explained by quality report.")

        except Exception as e:
            logging.exception(f"FAIL: Analysis pipeline crashed for race {race.race_uid}")
            failures += 1

    logging.info("--- Smoke Test Finished ---")
    if failures > 0:
        logging.error(f"Result: FAILED with {failures} assertion(s).")
        sys.exit(1)
    else:
        logging.info("Result: PASSED")
        sys.exit(0)

if __name__ == "__main__":
    main()
