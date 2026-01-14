from __future__ import annotations

import asyncio
import json
from datetime import datetime

from hippique_orchestrator.source_registry import source_registry
from hippique_orchestrator.data_contract import RaceSnapshotNormalized

RACE_URLS = {
    "trot": "https://www.boturfers.fr/course/1095423-r4c1-prix-de-riom",
    "plat": "https://www.boturfers.fr/course/1095381-r1c1-prix-des-iles-du-frioul",
}

async def run_acceptance_test():
    """
    Runs scraping acceptance tests against live URLs to validate data coverage.
    """
    report = {
        "test_run_at": datetime.utcnow().isoformat(),
        "results": [],
    }
    all_tests_ok = True

    for discipline, url in RACE_URLS.items():
        start_time = asyncio.get_event_loop().time()
        result_entry = {
            "discipline": discipline,
            "url": url,
            "phase": "H30",
            "source_used": None,
            "kpis": {},
            "errors": [],
            "passed": False,
        }

        print(f"--- Testing {discipline.upper()} race: {url} ---")

        try:
            snapshot: RaceSnapshotNormalized | None = await source_registry.get_snapshot(
                race_url=url, phase="H30"
            )
            
            duration = asyncio.get_event_loop().time() - start_time
            result_entry["duration_seconds"] = round(duration, 2)

            if not snapshot or not snapshot.runners:
                error_msg = "Snapshot could not be fetched or contains no runners."
                print(f"ERROR: {error_msg}")
                result_entry["errors"].append(error_msg)
                result_entry["source_used"] = snapshot.source_snapshot if snapshot else "N/A"
                report["results"].append(result_entry)
                all_tests_ok = False
                continue

            result_entry["source_used"] = snapshot.source_snapshot
            total_runners = len(snapshot.runners)

            # Calculate KPIs
            kpi_place_odds = sum(1 for r in snapshot.runners if r.odds_place and r.odds_place > 1.0) / total_runners
            kpi_musique = sum(1 for r in snapshot.runners if r.musique) / total_runners
            
            # For this initial test, we check stats from any source
            kpi_stats = sum(1 for r in snapshot.runners if r.stats.driver_rate or r.stats.trainer_rate) / total_runners
            kpi_chrono = sum(1 for r in snapshot.runners if r.stats.last_3_chrono or r.stats.record_rk) / total_runners
            
            # Drift KPI cannot be calculated with a single snapshot, so it's omitted here.

            result_entry["kpis"] = {
                "kpi_place_odds_coverage": round(kpi_place_odds, 2),
                "kpi_musique_coverage": round(kpi_musique, 2),
                "kpi_stats_coverage": round(kpi_stats, 2),
                "kpi_chrono_coverage": round(kpi_chrono, 2),
            }

            print(f"Source: {snapshot.source_snapshot}")
            print(f"KPIs: {result_entry['kpis']}")

            # Check thresholds
            test_passed = True
            if kpi_place_odds < 0.90:
                result_entry["errors"].append(f"Place odds coverage ({kpi_place_odds:.2f}) is below the 0.90 threshold.")
                test_passed = False
            
            if discipline == "trot" and kpi_musique < 0.60:
                result_entry["errors"].append(f"Musique coverage for trot ({kpi_musique:.2f}) is below the 0.60 threshold.")
                test_passed = False
            
            result_entry["passed"] = test_passed
            if not test_passed:
                all_tests_ok = False
                print("ERROR: Test failed thresholds.")
            else:
                print("SUCCESS: Test passed.")

        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            error_msg = f"An unexpected exception occurred: {e}"
            print(f"CRITICAL ERROR: {error_msg}")
            result_entry["errors"].append(error_msg)
            result_entry["duration_seconds"] = round(duration, 2)
            all_tests_ok = False
        
        report["results"].append(result_entry)

    # Write report
    with open("acceptance_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\n--- Acceptance Test Summary ---")
    print(json.dumps(report, indent=2))
    
    if not all_tests_ok:
        print("\nSome tests failed. Exiting with status 1.")
        exit(1)
    else:
        print("\nAll tests passed. Exiting with status 0.")
        exit(0)

if __name__ == "__main__":
    asyncio.run(run_acceptance_test())
