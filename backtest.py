#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest.py - Framework de backtesting pour la stratégie d'analyse hippique.

Ce script exécute la stratégie de pari sur un historique de courses pour en
mesurer la performance (ROI, EV, etc.).
"""

import argparse
import json
from pathlib import Path
from typing import Dict, Any

from simulate_wrapper import evaluate_combo


import shutil

import pipeline_run

def run_backtest_on_race(race_dir: Path) -> Dict[str, Any]:
    """
    Exécute le backtest pour une seule course.

    Args:
        race_dir: Le dossier contenant les données de la course.

    Returns:
        Un dictionnaire contenant les résultats du backtest pour la course.
    """
    print(f"Backtesting race in {race_dir}")

    # 1. Préparer l'environnement de test
    temp_dir = Path("temp_backtest")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    shutil.copy(race_dir / "snapshot_H-30.json", temp_dir / "h30.json")
    shutil.copy(race_dir / "snapshot_H-5.json", temp_dir / "h5.json")

    # Créer des fichiers de stats et partants vides pour satisfaire le pipeline
    (temp_dir / "stats_je.json").write_text("{}")
    (temp_dir / "partants.json").write_text("{\"runners\": []}")

    # 2. Exécuter le pipeline pour générer les tickets
    try:
        pipeline_results = pipeline_run.run_pipeline(str(temp_dir), budget=5.0)
        tickets = pipeline_results.get("reporting", {}).get("tickets", [])
    except Exception as e:
        print(f"[ERREUR] Le pipeline a échoué pour {race_dir}: {e}")
        return {"race": race_dir.name, "error": str(e)}

def calculate_sp_profit(ticket: Dict[str, Any], results: Dict[str, Any]) -> float:
    """
    Calcule le gain/perte pour un ticket Simple Placé (SP).
    """
    profit = -ticket["stake"]
    winning_horses = results["arrivee"]
    for leg in ticket["legs"]:
        if leg["horse"] in winning_horses:
            profit += leg["stake"] * leg["odds"]
    return profit

def calculate_cp_profit(ticket: Dict[str, Any], results: Dict[str, Any]) -> float:
    """
    Calcule le gain/perte pour un ticket Couplé Placé (CP).
    """
    profit = -ticket["stake"]
    winning_horses = results["arrivee"]
    
    chosen_horses = [leg["horse"] for leg in ticket["legs"]]
    
    # Check if at least two of the chosen horses are in the first three places
    num_winning_horses = 0
    for horse in chosen_horses:
        if horse in winning_horses[:3]:
            num_winning_horses += 1
    
    if num_winning_horses >= 2:
        combo_results = evaluate_combo([ticket], bankroll=ticket["stake"])
        profit += combo_results.get("payout_expected", 0)
        
    return profit

def calculate_trio_profit(ticket: Dict[str, Any], results: Dict[str, Any]) -> float:
    """
    Calcule le gain/perte pour un ticket Trio.
    """
    profit = -ticket["stake"]
    winning_horses = results["arrivee"]
    
    chosen_horses = [leg["horse"] for leg in ticket["legs"]]
    
    # Check if the three chosen horses are in the first three places
    if set(chosen_horses) == set(winning_horses[:3]):
        # The payout for a Trio bet is not straightforward to calculate from the odds.
        # For now, I will assume a fixed payout of 50 for a winning Trio ticket.
        # This is a limitation that I will address later.
        profit += 50
        
    return profit

    # 3. Calculer les gains/pertes
    with open(race_dir / "results.json", "r") as f:
        results = json.load(f)

    total_profit = 0
    for ticket in tickets:
        if ticket["kind"] == "SP_DUTCHING":
            total_profit += calculate_sp_profit(ticket, results)
        elif ticket["kind"] == "CP":
            total_profit += calculate_cp_profit(ticket, results)
        elif ticket["kind"] == "TRIO":
            total_profit += calculate_trio_profit(ticket, results)
        # TODO: Implement profit/loss calculation for other types of bets.

    # 4. Nettoyer l'environnement de test
    shutil.rmtree(temp_dir)

    return {"race": race_dir.name, "tickets": tickets, "profit": total_profit}


def main() -> None:
    """Point d'entrée du script de backtesting."""
    parser = argparse.ArgumentParser(
        description="Framework de backtesting pour la stratégie d'analyse hippique."
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Le dossier contenant les données historiques de courses."
    )
    args = parser.parse_args()

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
            race_results = run_backtest_on_race(race_dir)
            results.append(race_results)
            if "profit" in race_results:
                total_profit += race_results["profit"]
            if "tickets" in race_results:
                for ticket in race_results["tickets"]:
                    total_stake += ticket["stake"]
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
