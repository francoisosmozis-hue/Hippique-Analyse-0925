# scripts/calculate_roi.py

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import itertools

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from hippique_orchestrator import firestore_client

def get_manual_results(race_id: str) -> dict[str, list[int]]:
    """
    Placeholder function to manually input the race results.
    """
    results = {}
    print("\n" + "-"*30)
    print(f"Enter winning numbers for {race_id}")
    print("(e.g., '1,2,3' or just '1' for SP. Press Enter to skip a bet type)")
    
    try:
        sp_str = input("Simple Placé (Top 3): ")
        if sp_str:
            results["SP"] = sorted([int(n.strip()) for n in sp_str.split(",")])

        cg_str = input("Couplé Gagnant (Top 2, order irrelevant): ")
        if cg_str:
            results["CG"] = sorted([int(n.strip()) for n in cg_str.split(",")])

        trio_str = input("Trio (Top 3, order irrelevant): ")
        if trio_str:
            results["TRIO"] = sorted([int(n.strip()) for n in trio_str.split(",")])
            
        ze4_str = input("ZE4 (Top 4, order irrelevant): ")
        if ze4_str:
            results["ZE4"] = sorted([int(n.strip()) for n in ze4_str.split(",")])

    except (ValueError, TypeError):
        print("Invalid input. Skipping race.")
        return {}
        
    return results

def is_winner(ticket_type: str, ticket_horses: list[int], results: dict[str, list[int]]) -> bool:
    """
    Determines if a ticket is a winner based on the results.
    """
    if ticket_type == "SP_DUTCHING":
        # Dutching wins if ANY of the horses placed
        return any(h in results.get("SP", []) for h in ticket_horses)
        
    elif ticket_type in ["CPL", "CG"]:
        if "CG" not in results: return False
        # Must match the top 2 exactly
        return set(ticket_horses) == set(results["CG"])

    elif ticket_type == "TRIO":
        if "TRIO" not in results: return False
        # Must match the top 3 exactly
        return set(ticket_horses) == set(results["TRIO"])
        
    elif ticket_type == "ZE4":
        if "ZE4" not in results: return False
        # Must match the top 4 exactly
        return set(ticket_horses) == set(results["ZE4"])

    return False

def get_ticket_payout(ticket_type: str, ticket, results: dict) -> float:
    """
    For dutching, finds the payout of the winning horse. For others, asks manually.
    """
    if ticket_type == "SP_DUTCHING":
        winning_horse_num = next((h for h in ticket["horses"] if h in results.get("SP", [])), None)
        if winning_horse_num:
            # In a real scenario, you'd need the odds of the winning horse.
            # Here we simplify and ask for the dutched payout.
            try:
                return float(input(f"  -> SP Dutching WIN! Enter total payout for this bet: "))
            except (ValueError, TypeError):
                return 0.0
        return 0.0

    # For other combos, we assume one payout for the winning combination
    try:
        return float(input(f"  -> {ticket_type} WIN! Enter payout for this bet: "))
    except (ValueError, TypeError):
        return 0.0

def calculate_roi(start_date: str, end_date: str):
    """
    Calculates the real ROI for a given date range.
    """
    print(f"Analyzing performance from {start_date} to {end_date}")
    
    if not firestore_client.is_firestore_enabled():
        print("Firestore is not enabled. Please configure your environment.")
        return

    # Fetch all documents in the date range
    docs = []
    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_date_dt = datetime.strptime(end_date, "%Y-%m-%d")
    while current_date <= end_date_dt:
        date_str = current_date.strftime("%Y-%m-%d")
        print(f"Fetching data for {date_str}...")
        docs.extend(firestore_client.get_races_by_date_prefix(date_str))
        current_date += timedelta(days=1)

    if not docs:
        print("No documents found in the specified date range.")
        return

    # --- Analysis ---
    total_staked = 0.0
    total_returned = 0.0
    staked_by_type = defaultdict(float)
    returned_by_type = defaultdict(float)
    
    for doc in sorted(docs, key=lambda x: x.get("id", "")):
        race_id = doc.get("id", "UnknownRace")
        analysis = doc.get("tickets_analysis")
        
        if not analysis or analysis.get("abstain"):
            continue
            
        # Get real results for this race
        results = get_manual_results(race_id)
        if not results:
            print(f"Skipping race {race_id} due to no results provided.")
            continue

        for ticket in analysis.get("tickets", []):
            stake = ticket.get("stake", 0.0)
            ticket_type = ticket.get("type")
            
            total_staked += stake
            staked_by_type[ticket_type] += stake
            
            ticket_horses = ticket.get("horses") or ticket.get("combos", [[]])[0]

            if is_winner(ticket_type, ticket_horses, results):
                payout = get_ticket_payout(ticket_type, ticket, results)
                total_returned += payout
                returned_by_type[ticket_type] += payout

    # --- Reporting ---
    print("\n" + "="*50)
    print("ROI Analysis Summary")
    print("="*50)
    
    roi = (total_returned - total_staked) / total_staked if total_staked > 0 else 0.0
    
    print(f"Period: {start_date} to {end_date}")
    print(f"Total Staked:   {total_staked:.2f} €")
    print(f"Total Returned: {total_returned:.2f} €")
    print(f"Net Profit/Loss: {total_returned - total_staked:+.2f} €")
    print(f"TOTAL ROI:      {roi:+.2%}")
    
    print("\n--- Performance by Bet Type ---")
    all_bet_types = set(staked_by_type.keys()) | set(returned_by_type.keys())
    for bet_type in sorted(list(all_bet_types)):
        stake = staked_by_type.get(bet_type, 0.0)
        ret = returned_by_type.get(bet_type, 0.0)
        roi_type = (ret - stake) / stake if stake > 0 else 0.0
        print(f"\n- {bet_type}:")
        print(f"  - Staked:   {stake:.2f} €")
        print(f"  - Returned: {ret:.2f} €")
        print(f"  - ROI:      {roi_type:+.2%}")
        
    print("="*50)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calculate real ROI based on stored tickets and manual results.")
    parser.add_argument("--start-date", type=str, required=True, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="End date in YYYY-MM-DD format (default: today).")
    
    args = parser.parse_args()
    
    calculate_roi(args.start_date, args.end_date)
