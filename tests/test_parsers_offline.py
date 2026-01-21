# tests/test_parsers_offline.py
import json
from datetime import date
from tests.providers.file_based_provider import FileBasedProvider

def test_parser_produces_expected_dto():
    """
    Golden test: Uses the FileBasedProvider to parse a local HTML file
    and compares the resulting DTO to a pre-defined 'golden' JSON file.
    """
    # 1. Setup
    provider = FileBasedProvider()
    programme = provider.fetch_programme(for_date=date(2025, 1, 20))
    race_to_test = programme[0]

    # 2. Execution: Parse the H5 fixture
    _, snapshot_dto = provider.fetch_race_details(race_to_test, phase="H5")
    
    # Convert DTO to a dict for comparison, excluding dynamic timestamp
    result_dict = snapshot_dto.dict(exclude={'timestamp_utc'})

    # 3. Verification: Compare with the golden file
    with open("tests/fixtures/json_expected/boturfers/2025-01-20/R1C1__H5.json") as f:
        expected_dict = json.load(f)

    # The snapshot in the golden file doesn't include the overround, so we exclude it.
    result_dict.pop("overround_place", None)
    
    assert result_dict == expected_dict