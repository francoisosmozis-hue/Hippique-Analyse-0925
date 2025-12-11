# scripts/analyse_payout_drift.py

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from hippique_orchestrator import firestore_client


def get_manual_payout(race_id: str, ticket_type: str) -> float | None:
    """
    Placeholder function to manually input real-world payouts.
    In a real implementation, you might connect to a results API.
    """
    try:
        payout_str = input(f"Enter REAL payout for {race_id} [{ticket_type}] (or press Enter to skip): ")
        if not payout_str:
            return None
        return float(payout_str)
    except (ValueError, TypeError):
        print("Invalid input. Skipping.")
        return None

def analyze_drift(date: str):
    """
    Analyzes the drift between estimated and real payouts for a given date.
    """
    print(f"Fetching race analyses for date: {date}")

    if not firestore_client.is_firestore_enabled():
        print("Firestore is not enabled. Please configure your environment.")
        return

    race_documents = firestore_client.get_races_by_date_prefix(date)

    if not race_documents:
        print(f"No race documents found for {date}.")
        return

    drifts = {} # { "TRIO": [0.1, -0.05], "ZE4": [0.2] }

    for doc in race_documents:
        race_id = doc.get("id", "UnknownRace")
        analysis = doc.get("tickets_analysis")

        if not analysis or analysis.get("abstain"):
            continue

        for ticket in analysis.get("tickets", []):
            ticket_type = ticket.get("type")
            if not ticket_type or ticket_type.startswith("SP_"):
                continue # Skip Simple Placé bets

            estimated_payout = ticket.get("payout_est")
            if not estimated_payout:
                continue

            print("\n" + "="*30)
            print(f"Race: {race_id}")
            print(f"Ticket Type: {ticket_type}")
            print(f"Estimated Payout: {estimated_payout:.2f} €")

            real_payout = get_manual_payout(race_id, ticket_type)

            if real_payout is not None:
                # Drift = (Real - Estimated) / Estimated
                drift = (real_payout - estimated_payout) / estimated_payout

                if ticket_type not in drifts:
                    drifts[ticket_type] = []
                drifts[ticket_type].append(drift)

                print(f"  -> Drift: {drift:+.2%}")

    print("\n" + "="*50)
    print("Drift Analysis Summary")
    print("="*50)

    if not drifts:
        print("No combo bets with real payouts were analyzed.")
        return

    for ticket_type, values in drifts.items():
        avg_drift = sum(values) / len(values)
        print(f"Bet Type: {ticket_type}")
        print(f"  - Observations: {len(values)}")
        print(f"  - Average Drift: {avg_drift:+.2%}")

        if avg_drift > 0.05:
            print(f"  - SUGGESTION: Payouts are underestimated. Consider DECREASING the weight for '{ticket_type}' in payout_calibration.yaml.")
        elif avg_drift < -0.05:
            print(f"  - SUGGESTION: Payouts are overestimated. Consider INCREASING the weight for '{ticket_type}' in payout_calibration.yaml.")
        else:
            print("  - SUGGESTION: Calibration seems reasonable.")
    print("="*50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze payout drift for exotic bets.")
    parser.add_argument(
        "--date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Date to analyze in YYYY-MM-DD format (default: today)."
    )
    args = parser.parse_args()

    analyze_drift(args.date)
