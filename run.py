# run.py
import logging
import json
import os
from datetime import date

from hippique_orchestrator.analysis_pipeline import run_analysis_for_race
from hippique_orchestrator.providers.aggregate import AggregateProvider
from tests.providers.file_based_provider import FileBasedProvider # Using test provider for demo

# --- Config ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
TARGET_DATE = date.today()
DUMMY_GPI_CONFIG = {"budget": 100, "roi_min_global": 0.05}
ANALYSIS_CACHE_PATH = "artifacts/daily_analysis.json"

def main():
    """
    Main script to run the analysis for a given date and save results to cache.
    """
    logging.info(f"--- Starting Analysis Run for {TARGET_DATE} ---")

    # For this run, we use the FileBasedProvider.
    # In production, you would instantiate your live providers here.
    file_provider = FileBasedProvider()
    agg_provider = AggregateProvider(providers=[file_provider])

    programme = agg_provider.fetch_programme(for_date=TARGET_DATE)
    if not programme:
        logging.warning("No races found in programme. Exiting.")
        return

    all_results = {}
    for race in programme:
        result = run_analysis_for_race(race, agg_provider, DUMMY_GPI_CONFIG)
        all_results[result.race_uid] = result.dict()

    logging.info(f"Analysis complete. Saving {len(all_results)} result(s) to cache.")
    os.makedirs("artifacts", exist_ok=True)
    with open(ANALYSIS_CACHE_PATH, "w") as f:
        json.dump(all_results, f, indent=2)

    logging.info(f"--- Run Finished ---")

if __name__ == "__main__":
    main()
