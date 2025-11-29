import logging
import os
import pathlib
import sys
from pathlib import Path  # Add this import
from typing import Any

import yaml

# --- Project Root and Configuration Setup ---
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CALIB_PATH = PROJECT_ROOT / "config" / "payout_calibration.yaml"
try:
    CALIB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CALIB_PATH.exists():
        CALIB_PATH.write_text(
            "version: 1\n"
            "exotic_weights:\n"
            "  TRIO: 1.0\n"
            "  ZE4: 1.0\n"
            "  CPL: 1.0\n"
        )
    os.environ["PAYOUT_CALIBRATION_PATH"] = str(CALIB_PATH)
except Exception as e:
    logging.getLogger(__name__).warning(f"Calibration auto-init failed: {e}")

# --- Import core logic with fallbacks ---
try:
    from hippique_orchestrator.kelly import calculate_kelly_fraction
    from src.overround import adaptive_cap, compute_overround_place
    from hippique_orchestrator.simulate_wrapper import evaluate_combo
    from analysis_utils import compute_overround_cap
except ImportError:
    logging.warning("One or more core modules not found. Using mock implementations.")
    def compute_overround_place(runners): return 1.20
    def adaptive_cap(p_place, volatility, base_cap=0.6): return base_cap
    def calculate_kelly_fraction(odds, prob, fraction=1.0): return fraction * (odds * prob - 1) / (odds - 1)
    def evaluate_combo(**kwargs): return {"status": "insufficient_data", "message": "Simulation unavailable"}
    def compute_overround_cap(*args, **kwargs): return 1.0

# --- Logging ---
logger = logging.getLogger(__name__)

def load_gpi_config(config_path: pathlib.Path) -> dict[str, Any]:
    """Loads the GPI YAML configuration."""
    if not config_path.exists():
        logger.error(f"GPI Config not found at {config_path}")
        raise FileNotFoundError(f"GPI Config not found at {config_path}")
    with open(config_path) as f:
        return yaml.safe_load(f)

def generate_tickets(
    snapshot_data: dict[str, Any],
    gpi_config: dict[str, Any],
    budget: float,
    calibration_path: str,
    allow_heuristic: bool = False
) -> dict[str, Any]:
    """
    Pure logic for ticket generation based on GPI v5.1 guardrails.
    This function is I/O-free.
    """
    runners = snapshot_data.get("runners", [])
    if not runners:
        return {"abstain": True, "tickets": [], "roi_global_est": 0, "message": "No runners found in snapshot"}

    # --- GPI v5.1 Guardrails ---
    sp_tickets = []
    combo_tickets = []

    # 1. Overround Guard & Calibration Check for Exotics
    overround_place = snapshot_data.get("market", {}).get("overround_place", compute_overround_place(runners))

    calibration_available = calibration_path and pathlib.Path(calibration_path).exists()
    if not calibration_available:
        logger.warning(f"Payout calibration file not found at {calibration_path}. Abstaining from combos.")
        allow_exotics = False
    else:
        allow_exotics = overround_place <= gpi_config["overround_max_exotics"]

    if overround_place > gpi_config["overround_max_exotics"]:
        logger.warning(f'Overround is high ({overround_place:.2f} > {gpi_config["overround_max_exotics"]}). Disabling exotic bets.')
        allow_exotics = False

    # 2. SP Dutching ROI & Volatility Guard
    sp_candidates = []
    sp_dutching_config = gpi_config["tickets"]["sp_dutching"]
    odds_min, odds_max = sp_dutching_config["odds_range"]

    for r in runners:
        if not all(k in r for k in ["p_place", "cote", "volatility"]):
            continue

        roi_sp = (r["p_place"] * r["cote"]) - 1
        if odds_min <= r["cote"] <= odds_max and roi_sp >= gpi_config["roi_min_sp"]:
            discipline_val = snapshot_data.get("discipline")
            partants_val = len(runners)
            volatility_cap = adaptive_cap(discipline_val, partants_val, base_cap=gpi_config["max_vol_per_horse"])
            
            if r.get("volatility", 0) <= volatility_cap:
                r['roi_sp'] = roi_sp
                sp_candidates.append(r)

    if len(sp_candidates) >= sp_dutching_config["legs_min"]:
        sp_candidates.sort(key=lambda r: r['roi_sp'], reverse=True)
        dutch_horses = sp_candidates[:min(len(sp_candidates), sp_dutching_config["legs_max"])]

        sp_budget = min(budget, gpi_config["budget_cap_eur"]) * gpi_config["tickets"]["sp_dutching"]["budget_ratio"]
        stakes = {}
        
        # Using Kelly criterion for stake allocation
        raw_kelly_stakes = {}
        total_kelly_fraction = 0
        for r in dutch_horses:
            stake_fraction = calculate_kelly_fraction(r["cote"], r["p_place"], fraction=sp_dutching_config["kelly_frac"])
            if stake_fraction > 0:
                raw_kelly_stakes[r["num"]] = stake_fraction
                total_kelly_fraction += stake_fraction
        
        if total_kelly_fraction > 0:
            for num, frac in raw_kelly_stakes.items():
                stakes[num] = sp_budget * (frac / total_kelly_fraction)
            
            total_sp_stake = sum(stakes.values())
            if total_sp_stake > 0.1: # Min stake
                sp_tickets.append({
                    "type": "SP_DUTCHING",
                    "stake": round(total_sp_stake, 2),
                    "roi_est": sum(r['roi_sp'] * (stakes[r['num']]/total_sp_stake) for r in dutch_horses if r['num'] in stakes),
                    "horses": [h["num"] for h in dutch_horses if h['num'] in stakes],
                    "details": {num: round(s, 2) for num, s in stakes.items()}
                })

    # 3. Combo Guard (EV & Payout) - Max 1 combo ticket
    if allow_exotics and len(runners) >= 4 and len(sp_tickets) > 0 and len(combo_tickets) == 0:
        remaining_budget = min(budget, gpi_config["budget_cap_eur"]) - sum(t['stake'] for t in sp_tickets)
        if remaining_budget > 0.5:
            combo_cfg = gpi_config["tickets"]["exotics"]
            combo_selection = [r["num"] for r in sorted(runners, key=lambda x: x.get('p_place', 0), reverse=True)[:combo_cfg.get("legs_count", 4)]]

            combo_ticket = {
                "type": combo_cfg.get("type", "TRIO"),
                "legs": combo_selection,
                "stake": min(remaining_budget, combo_cfg.get("stake_eur", 2.0))
            }
            combo_eval = evaluate_combo(tickets=[combo_ticket], bankroll=budget, calibration=calibration_path, allow_heuristic=allow_heuristic)

            if combo_eval.get("status") == "ok" and combo_eval.get("roi", 0) >= gpi_config["ev_min_combo"] and combo_eval.get("payout_expected", 0) >= gpi_config["payout_min_combo"]:
                combo_tickets.append({
                    "type": combo_ticket["type"], "stake": combo_ticket["stake"], "roi_est": combo_eval["roi"],
                    "combos": [combo_selection], "payout_est": combo_eval["payout_expected"],
                })
            elif combo_eval.get("status") == "insufficient_data":
                logger.warning("Combo rejected: insufficient data for simulation (no calibration).")

    # 4. Global ROI & Abstention Guard
    all_tickets = sp_tickets + combo_tickets
    total_stake = sum(t["stake"] for t in all_tickets)
    roi_global_est = sum(t["roi_est"] * t["stake"] for t in all_tickets) / total_stake if total_stake > 0 else 0

    abstain_reason = ""
    if not all_tickets or roi_global_est < gpi_config["roi_min_sp"]:
        abstain_reason = "No valid tickets found" if not all_tickets else f'Global ROI ({roi_global_est:.2%}) is below threshold.'
        all_tickets = []
        roi_global_est = 0

    # --- Return Result ---
    return {
        "abstain": not all_tickets,
        "tickets": all_tickets,
        "roi_global_est": round(roi_global_est, 4),
        "message": abstain_reason
    }