import argparse
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from hippique_orchestrator.pipeline_run import generate_tickets

logging.basicConfig(level=logging.INFO)

def run_backtest_on_race(race_dir: Path, gpi_config: dict[str, Any]) -> dict[str, Any]:
    """
    Exécute le backtest pour une seule course.
    """
    print(f"Backtesting race in {race_dir}")

    with open(race_dir / "snapshot_H-5.json") as f:
        snapshot_data = json.load(f)
    with open(race_dir / "snapshot_H-30.json") as f:
        h30_snapshot_data = json.load(f)
    with open(race_dir / "results.json") as f:
        results = json.load(f)

    gpi_config["h30_snapshot_data"] = h30_snapshot_data
    gpi_config["je_stats"] = {}
    gpi_config["calibration_data"] = {}

    def mock_calculate_adjusted_probabilities(runners, config):
        # Directly use p_finale from snapshot, bypassing complex adjustments
        return runners, ["Probabilities patched for backtest"]

    with patch(
        "hippique_orchestrator.pipeline_run._calculate_adjusted_probabilities",
        mock_calculate_adjusted_probabilities,
    ):
        try:
            pipeline_results = generate_tickets(snapshot_data, gpi_config)
            tickets = pipeline_results.get("tickets", [])
        except Exception as e:
            print(f"[ERREUR] Le pipeline a échoué pour {race_dir}: {e}")
            return {"race": race_dir.name, "error": str(e), "profit": 0, "tickets": []}

    total_profit = 0
    for ticket in tickets:
        if ticket["type"] == "SP_DUTCHING":
            total_profit += calculate_sp_profit(ticket, results, snapshot_data['runners'])
        # TODO: Add other ticket types

    return {"race": race_dir.name, "tickets": tickets, "profit": total_profit}


def calculate_sp_profit(ticket: dict[str, Any], results: dict[str, Any], runners: list) -> float:
    """
    Calcule le gain/perte pour un ticket Simple Placé (SP).
    """
    profit = -ticket["stake"]
    winning_horses = results["arrivee"]
    for horse_num, stake in ticket.get("details", {}).items():
        # Find the horse in the runners to get the odds
        runner = next((r for r in runners if str(r.get("num")) == str(horse_num)), None)
        if runner:
            if str(horse_num) in winning_horses[:3]:
                profit += stake * runner["odds_place"]
    return profit

def main() -> None:
    """Point d'entrée du script de backtesting."""
    parser = argparse.ArgumentParser(
        description="Framework de backtesting pour la stratégie d'analyse hippique."
    )
    parser.add_argument(
        "--data-dir", required=True, help="Le dossier contenant les données historiques de courses."
    )
    parser.add_argument(
        "--config", default="config/gpi_v52.yml", help="Fichier de configuration YAML à utiliser."
    )
    args = parser.parse_args()

    # Charger la configuration
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERREUR] Le fichier de configuration n'existe pas: {config_path}")
        return
    with open(config_path) as f:
        gpi_config = yaml.safe_load(f)

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(f"[ERREUR] Le dossier de données n'existe pas: {data_dir}")
        return

    results = []
    total_profit = 0
    total_stake = 0
    num_bets = 0

    for race_dir in data_dir.iterdir():
        if race_dir.is_dir():
            race_results = run_backtest_on_race(race_dir, gpi_config)
            results.append(race_results)

            profit = race_results.get("profit", 0)
            total_profit += profit

            for ticket in race_results.get("tickets", []):
                total_stake += ticket.get("stake", 0)

            if race_results.get("tickets"):
                num_bets += 1

    roi = (total_profit / total_stake) * 100 if total_stake > 0 else 0

    report = {
        "num_races": len(results),
        "num_bets": num_bets,
        "total_stake": total_stake,
        "total_profit": total_profit,
        "roi_percent": roi,
        "races": results,
    }

    with open("backtest_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Backtesting terminé. Le rapport a été sauvegardé dans backtest_report.json")
if __name__ == "__main__":
    main()
