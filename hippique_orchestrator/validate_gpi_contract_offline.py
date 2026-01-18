import sys
from hippique_orchestrator import zoneturf_client

def main():
    """
    Main function to validate GPI contract offline.
    """
    fixture_path = "tests/fixtures/zeturf_race.html"
    
    try:
        with open(fixture_path, "r", encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        print(f"Error: Fixture file not found at {fixture_path}", file=sys.stderr)
        print("Please create and populate the fixture file.", file=sys.stderr)
        sys.exit(1)

    if not html_content:
        print(f"Error: Fixture file {fixture_path} is empty.", file=sys.stderr)
        print("Please populate the fixture file with ZEturf race page HTML.", file=sys.stderr)
        sys.exit(1)

    soup = zoneturf_client.parse_html(html_content)
    snapshot = zoneturf_client.parse_race_data(soup)
    
    quality_score = zoneturf_client.calculate_quality_score(snapshot)
    odds_place_ratio = zoneturf_client.calculate_odds_place_ratio(snapshot)
    
    print(f"Quality Score: {quality_score:.2f}")
    print(f"Odds Place Ratio: {odds_place_ratio:.2f}")
    
    quality_threshold = 0.85
    odds_ratio_threshold = 0.90
    
    success = True
    if quality_score < quality_threshold:
        print(f"FAIL: Quality score {quality_score:.2f} is below the threshold of {quality_threshold}", file=sys.stderr)
        success = False
        
    if odds_place_ratio < odds_ratio_threshold:
        print(f"FAIL: Odds place ratio {odds_place_ratio:.2f} is below the threshold of {odds_ratio_threshold}", file=sys.stderr)
        success = False
        
    if success:
        print("SUCCESS: All metrics meet the required thresholds.")
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
