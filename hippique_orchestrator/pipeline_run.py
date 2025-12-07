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
except Exception as e:
    logging.getLogger(__name__).warning(f"Calibration auto-init failed: {e}")

# --- Import core logic with fallbacks ---
try:
    from hippique_orchestrator.kelly import calculate_kelly_fraction
    from hippique_orchestrator.overround import adaptive_cap, compute_overround_place
    from hippique_orchestrator.simulate_wrapper import evaluate_combo
    from hippique_orchestrator.analysis_utils import compute_overround_cap
except ImportError:
    logging.warning("One or more core modules not found. Using mock implementations.")
    def calculate_kelly_fraction(odds, prob, fraction=1.0): return fraction * (odds * prob - 1) / (odds - 1)
    def evaluate_combo(**kwargs): return {"status": "insufficient_data", "message": "Simulation unavailable"}
    def compute_overround_cap(*args, **kwargs): return 1.0
    def compute_overround_place(*args, **kwargs): return 1.0
    def adaptive_cap(*args, **kwargs): return 1.0

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
    calibration_data: dict[str, Any],
    allow_heuristic: bool = False
) -> dict[str, Any]:
    """
    Logique pure pour la génération de tickets basée sur les garde-fous GPI v5.2.
    Cette fonction est sans I/O, à l'exception d'un fichier temporaire pour la calibration.
    """
    # Existing logic would go here once dummy is removed
    runners = snapshot_data.get("runners", [])
    if not runners:
        return {
            "gpi_decision": "Abstain: No runners found in snapshot",
            "tickets": [],
            "roi_global_est": 0,
            "message": "No runners found in snapshot"
        }
    # ... (rest of existing logic for actual ticket generation)

    # TEMPORARY: Return a dummy ticket to confirm pipeline flow if runners are present.
    # This allows verification that Firestore saving and /pronostics endpoint
    # correctly process a race with tickets.
    # logger.warning("Returning TEMPORARY hardcoded ticket to confirm pipeline flow.")
    # temp_ticket = {
    #     "type": "TEMP_TEST_TICKET",
    #     "stake": 1.00,
    #     "roi_est": 0.20,
    #     "horses": ["1", "2", "3"],
    #     "details": {"1": 0.4, "2": 0.3, "3": 0.3},
    #     "message": "Temporary ticket for pipeline verification."
    # }
    # return {
    #     "gpi_decision": "Play (Temporary Ticket)",
    #     "tickets": [temp_ticket],
    #     "roi_global_est": 0.20,
    #     "message": "Temporary ticket for pipeline verification."
    # }
    # TODO: Implement actual ticket generation logic here.
    return {
        "gpi_decision": "Abstain: Ticket generation logic not implemented",
        "tickets": [],
        "roi_global_est": 0,
        "message": "Ticket generation logic not implemented"
    }

