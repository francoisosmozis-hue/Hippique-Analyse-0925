# run_pipeline.py
import logging
from datetime import date
from hippique_orchestrator.analysis_pipeline import run_analysis_for_date
from tests.providers.file_based_provider import FileBasedProvider

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    print("Running analysis pipeline with FileBasedProvider to generate cache...")
    
    # Dummy config
    gpi_config = {"budget": 100, "roi_min_global": 0.05}
    
    # Use the test provider to run offline
    provider = FileBasedProvider()
    
    run_analysis_for_date(
        for_date=date.today(),
        providers=[provider],
        gpi_config=gpi_config
    )
    print("Cache file 'artifacts/daily_analysis.json' created successfully.")
