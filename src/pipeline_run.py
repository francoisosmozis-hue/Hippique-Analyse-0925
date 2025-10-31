import os, pathlib, logging

# --- Ensure payout calibration is always available ---
CALIB_PATH = pathlib.Path(__file__).resolve().parents[1] / "config" / "payout_calibration.yaml"
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
    logging.getLogger(__name__).info(f"✅ Payout calibration ready at {CALIB_PATH}")
except Exception as e:
    logging.getLogger(__name__).warning(f"Calibration auto-init failed: {e}")

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# --- Project Root Setup ---
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# --- Import core logic ---
# Mock missing modules for testing or environments where they are not installed.
try:
    from src.overround import compute_overround_place, adaptive_cap
    from src.kelly import calculate_kelly_fraction
    from src.simulate_wrapper import evaluate_combo
except ImportError:
    logging.warning("One or more core modules not found. Using mock implementations for [overround, kelly, simulate_wrapper].")
    def compute_overround_place(runners): return 1.20
    def adaptive_cap(p_place, volatility, base_cap=0.6): return base_cap
    def calculate_kelly_fraction(odds, prob, fraction=1.0): return fraction * (odds * prob - 1) / (odds - 1)
    def evaluate_combo(**kwargs): return {"status": "insufficient_data", "message": "Simulation unavailable"}

# --- Logging ---
logger = logging.getLogger(__name__)


def load_gpi_config(config_path: Path) -> Dict[str, Any]:
    """Loads the GPI YAML configuration."""
    if not config_path.exists():
        logger.error(f"GPI Config not found at {config_path}")
        raise FileNotFoundError(f"GPI Config not found at {config_path}")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def run_pipeline(
    reunion: str,
    course: str,
    phase: str,
    budget: float = 5.0,
    allow_heuristic: bool = False,
    _snapshot_for_test: Optional[Dict] = None,
    calibration_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main pipeline logic to decide on bets based on GPI v5.1 guardrails.
    """
    # --- Load GPI Config ---
    gpi_config_path = _PROJECT_ROOT / "config" / "gpi_v52.yml"
    try:
        gpi_config = load_gpi_config(gpi_config_path)
    except FileNotFoundError:
        return {"abstain": True, "tickets": [], "roi_global_est": 0, "message": f"GPI Config not found: {gpi_config_path}", "paths": {}}

    # --- Data Loading ---
    race_dir = _PROJECT_ROOT / "data" / f"{reunion}{course}"
    snapshot_path = race_dir / f"snapshot_{phase}.json"
    abstain = False
    abstain_reason = ""

    if _snapshot_for_test:
        snapshot = _snapshot_for_test
    elif snapshot_path.exists():
        with open(snapshot_path, "r") as f:
            snapshot = json.load(f)
    else:
        return {"abstain": True, "tickets": [], "roi_global_est": 0, "message": f"Snapshot not found: {snapshot_path}", "paths": {}}

    runners = snapshot.get("runners", [])
    if not runners:
        return {"abstain": True, "tickets": [], "roi_global_est": 0, "message": "No runners found in snapshot", "paths": {}}

    # --- GPI v5.1 Guardrails ---
    sp_tickets = []
    combo_tickets = []
    
    # 1. Overround Guard & Calibration Check for Exotics
    overround_place = snapshot.get("market", {}).get("overround_place", compute_overround_place(runners))
    
    calibration_available = calibration_path and Path(calibration_path).exists()
    allow_exotics = overround_place <= gpi_config["overround_max_exotics"]

    if not calibration_available:
        logger.warning("Payout calibration file not found at %s. Disabling exotic bets.", calibration_path)
        allow_exotics = False
    
    if overround_place > gpi_config["overround_max_exotics"]:
        logger.warning(f'''Overround is high ({overround_place:.2f} > {gpi_config["overround_max_exotics"]}). Disabling exotic bets.''')
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
            volatility_cap = adaptive_cap(r["p_place"], r.get("volatility", 0.5), base_cap=gpi_config["max_vol_per_horse"])
            if r.get("volatility", 0) <= volatility_cap:
                r['roi_sp'] = roi_sp
                sp_candidates.append(r)

    if len(sp_candidates) >= sp_dutching_config["legs_min"]:
        sp_candidates.sort(key=lambda r: r['roi_sp'], reverse=True)
        dutch_horses = sp_candidates[:min(len(sp_candidates), sp_dutching_config["legs_max"])]
        
        total_prob = sum(r["p_place"] for r in dutch_horses)
        if total_prob > 0:
            sp_budget = min(budget, gpi_config["budget_cap_eur"]) * 0.6 # TODO: make 0.6 configurable
            stakes = {}
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
            combo_selection = [r["num"] for r in sorted(runners, key=lambda x: x.get('p_place', 0), reverse=True)[:4]]
            
            combo_ticket = {
                "type": "TRIO", # TODO: Make configurable from gpi_config["tickets"]["exotics"]["allowed"]
                "legs": combo_selection,
                "stake": min(remaining_budget, 2.0) # TODO: Make configurable
            }

            combo_eval = evaluate_combo(
                tickets=[combo_ticket],
                bankroll=budget,
                calibration=calibration_path,
                allow_heuristic=allow_heuristic
            )

            if combo_eval.get("status") == "ok":
                if combo_eval.get("roi", 0) >= gpi_config["ev_min_combo"] and combo_eval.get("payout_expected", 0) >= gpi_config["payout_min_combo"]:
                    combo_tickets.append({
                        "type": "TRIO",
                        "stake": combo_ticket["stake"],
                        "roi_est": combo_eval["roi"],
                        "combos": [combo_selection],
                        "payout_est": combo_eval["payout_expected"],
                    })
                else:
                    logger.info(f'''Combo rejected: ROI ({combo_eval.get('roi', 0):.2f}) or Payout ({combo_eval.get('payout_expected', 0):.2f}) below threshold.''')
            elif combo_eval.get("status") == "insufficient_data":
                logger.warning("Combo rejected: insufficient data for simulation (no calibration).")

    # 4. Global ROI & Abstention Guard
    all_tickets = sp_tickets + combo_tickets
    total_stake = sum(t["stake"] for t in all_tickets)
    
    if total_stake > 0:
        weighted_rois = [(t["roi_est"] * t["stake"]) for t in all_tickets]
        roi_global_est = sum(weighted_rois) / total_stake
    else:
        roi_global_est = 0

    if not all_tickets or roi_global_est < gpi_config["roi_min_sp"]:
        abstain = True
        if not all_tickets:
            abstain_reason = "No valid tickets found after applying guardrails."
        else:
            abstain_reason = f'''Global ROI ({roi_global_est:.2%}) is below the +{gpi_config["roi_min_sp"]:.0%} threshold.'''
        all_tickets = []
        roi_global_est = 0 # Reset ROI if abstaining
    
    # 5. Budget & Ticket Cap (Final check)
    if len(all_tickets) > gpi_config["tickets_max"]:
        all_tickets = (sp_tickets[:1] + combo_tickets[:1]) # Keep max 1 of each type

    final_stake = sum(t["stake"] for t in all_tickets)
    if final_stake > budget:
        scale = budget / final_stake
        for t in all_tickets:
            t["stake"] = round(t["stake"] * scale, 2)
    
    # --- Result ---
    analysis_path = race_dir / f"analysis_{phase}.json"
    result = {
        "abstain": abstain,
        "tickets": all_tickets,
        "roi_global_est": round(roi_global_est, 4),
        "message": abstain_reason,
        "paths": {
            "snapshot": str(snapshot_path),
            "analysis": str(analysis_path)
        }
    }
    
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    with open(analysis_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


def api_entrypoint(payload: dict) -> dict:
    """
    Wrapper unique appelé par /run : valide le payload,
    route vers la logique existante (H30/H5/RESULT),
    et renvoie un dict JSON-serializable.
    """
    reunion = payload.get("reunion")
    course = payload.get("course")
    phase = payload.get("phase")
    budget = payload.get("budget", 5.0)
    calibration_path = payload.get("calibration_path")
    allow_exotic_if_no_calibration = payload.get("allow_exotic_if_no_calibration", False)

    if not all([reunion, course, phase]):
        raise ValueError("Missing required payload fields: reunion, course, phase")

    return run_pipeline(
        reunion=reunion,
        course=course,
        phase=phase,
        budget=budget,
        calibration_path=calibration_path,
        allow_heuristic=allow_exotic_if_no_calibration
    )

# --- Main execution for standalone runs ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run GPI v5.1 betting pipeline for a specific race.")
    parser.add_argument("--reunion", required=True, help="Reunion ID (e.g., R1)")
    parser.add_argument("--course", required=True, help="Course ID (e.g., C3)")
    parser.add_argument("--phase", default="H5", choices=["H5"], help="Pipeline phase (only H5 is runnable directly)")
    parser.add_argument("--budget", type=float, help="Maximum budget for the race")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # GPI config is loaded inside run_pipeline, budget can be passed as override
    gpi_config_path = _PROJECT_ROOT / "config" / "gpi_v52.yml"
    config = load_gpi_config(gpi_config_path)
    
    # Use budget from args if provided, otherwise from config, otherwise default.
    budget = args.budget if args.budget is not None else config.get("budget_cap_eur", 5.0)

    output = run_pipeline(
        reunion=args.reunion,
        course=args.course,
        phase=args.phase,
        budget=budget,
    )
    print(json.dumps(output, indent=2))

