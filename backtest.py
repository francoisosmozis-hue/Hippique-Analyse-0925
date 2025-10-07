#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de backtesting pour évaluer la performance historique de la stratégie de paris.

Ce script simule l'exécution de la stratégie sur une période donnée et calcule
le retour sur investissement (ROI) en comparant les paris générés aux résultats réels.

Exemple d'utilisation :
python backtest.py \
    --start-date 2025-09-01 \
    --end-date 2025-09-30 \
    --data-dir /home/francoisosmozis/Hippique-Analyse-0925/data \
    --budget 100
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ajout du répertoire du projet au path pour permettre les imports relatifs
project_root = Path(__file__).resolve().parent
sys.path.append(str(project_root))


def parse_arguments() -> argparse.Namespace:
    """Parse les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(
        description="Backtest de la stratégie de paris hippiques."
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Date de début du backtest (format: YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="Date de fin du backtest (format: YYYY-MM-DD).",
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Chemin vers le répertoire racine des données (contenant les jours YYYYMMDD).",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=100.0,
        help="Budget quotidien alloué pour les paris.",
    )
    return parser.parse_args()


def get_race_results(race_dir: Path) -> Dict[str, Any] | None:
    """Charge les résultats d'une course depuis arrivee.json."""
    results_path = race_dir / "arrivee.json"
    if not results_path.exists():
        return None
    try:
        with results_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def calculate_pnl(tickets: List[Dict[str, Any]], results: Dict[str, Any]) -> Tuple[float, float]:
    """
    Calcule le Profit & Loss (P&L) pour une liste de tickets.

    Args:
        tickets: La liste des paris générés par p_finale.json.
        results: Les résultats de la course (depuis arrivee.json).

    Returns:
        Un tuple (pnl, total_wagered).
    """
    pnl = 0.0
    total_wagered = 0.0

    if not results or ("arrivee" not in results and "place" not in results):
        # Si pas de résultats, on considère les mises comme perdues
        for ticket in tickets:
            total_wagered += float(ticket.get("stake", 0.0))
        return -total_wagered, total_wagered

    # Utilise 'arrivee' pour les chevaux gagnants/places, fallback sur 'place'
    placed_horses_data = results.get("arrivee", results.get("place", []))
    placed_horses = {str(h["num"]) for h in placed_horses_data}
    
    for ticket in tickets:
        stake = float(ticket.get("stake", 0.0))
        total_wagered += stake
        bet_type = str(ticket.get("type", "")).upper()

        if bet_type in ("SP", "SIMPLE_PLACE"):
            # Pari Simple Placé
            legs = ticket.get("legs", [])
            if not legs:
                continue
            
            horse_num = str(legs[0].get("num"))
            if horse_num in placed_horses:
                # Le cheval est placé, trouver son rapport
                for h in placed_horses_data:
                    if str(h["num"]) == horse_num:
                        rapport = float(h.get("rapport", 0.0))
                        pnl += (stake * rapport) - stake
                        break
            else:
                pnl -= stake
        
        elif bet_type in ("CP", "COUPLE_PLACE", "COUPLE"):
            # Pari Couplé Placé
            legs = ticket.get("legs", [])
            if len(legs) != 2:
                continue

            horse1_num = str(legs[0].get("num"))
            horse2_num = str(legs[1].get("num"))

            if horse1_num in placed_horses and horse2_num in placed_horses:
                # Les deux chevaux sont dans les 3 premiers.
                # Le fichier arrivee.json ne semble pas contenir les rapports CP.
                # On utilise une estimation basée sur les cotes SP si disponibles.
                # Ceci est une LIMITATION et une source d'IMPRÉCISION.
                # Pour un backtest précis, il faudrait les vrais rapports CP.
                rapports_cp = results.get("rapports", {}).get("COUPLE_PLACE", {})
                # La clé du rapport peut être "H1-H2" ou "H2-H1"
                rapport_key1 = f"{horse1_num}-{horse2_num}"
                rapport_key2 = f"{horse2_num}-{horse1_num}"
                rapport_val = rapports_cp.get(rapport_key1) or rapports_cp.get(rapport_key2)

                if rapport_val:
                     pnl += (stake * float(rapport_val)) - stake
                else:
                    # Fallback si le rapport exact n'est pas trouvé
                    pnl -= stake # On considère le pari comme perdu
            else:
                pnl -= stake
        else:
            # Autres types de paris non gérés pour le moment
            pnl -= stake

    return pnl, total_wagered


def main():
    """Fonction principale du script de backtest."""
    args = parse_arguments()

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    data_dir = Path(args.data_dir)
    daily_budget = args.budget

    total_pnl = 0.0
    total_wagered = 0.0
    days_with_bets = 0
    
    orchestrator_script = project_root / "analyse_courses_du_jour_enrichie.py"

    print(f"Lancement du backtest du {start_date} au {end_date}")
    print("-" * 40)

    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y%m%d")
        day_dir = data_dir / date_str
        
        if not day_dir.is_dir():
            current_date += timedelta(days=1)
            continue

        print(f"\nTraitement du {current_date.strftime('%Y-%m-%d')}...")
        day_pnl = 0.0
        day_wagered = 0.0
        races_processed = 0

        race_dirs = sorted([d for d in day_dir.iterdir() if d.is_dir() and d.name.startswith("R")])

        for race_dir in race_dirs:
            # Étape 1: Exécuter l'orchestrateur pour générer p_finale.json
            # On simule ce qui se serait passé le jour J
            cmd = [
                sys.executable,
                str(orchestrator_script),
                "--rc-dir", str(race_dir),
                "--budget", str(daily_budget),
                "--kelly", "0.5" # Utilisation d'une fraction de Kelly standard
            ]
            
            try:
                # L'orchestrateur est verbeux, on capture la sortie pour ne pas polluer
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError:
                # Si le pipeline échoue pour une course, on le note et on continue
                continue

            # Étape 2: Charger les tickets générés
            p_finale_path = race_dir / "p_finale.json"
            if not p_finale_path.exists():
                continue
            
            try:
                with p_finale_path.open("r", encoding="utf-8") as f:
                    p_finale_data = json.load(f)
                tickets = p_finale_data.get("tickets", [])
                if not tickets:
                    continue
            except (json.JSONDecodeError, IOError):
                continue

            # Étape 3: Charger les résultats de la course
            results = get_race_results(race_dir)
            if not results:
                # Pas de fichier de résultat, on ne peut pas calculer le P&L
                # On considère les mises comme perdues pour être conservateur
                for ticket in tickets:
                    wagered = float(ticket.get("stake", 0.0))
                    day_wagered += wagered
                    day_pnl -= wagered
                continue

            # Étape 4: Calculer le P&L pour la course
            pnl, wagered = calculate_pnl(tickets, results)
            day_pnl += pnl
            day_wagered += wagered
            races_processed += 1

        if day_wagered > 0:
            days_with_bets += 1
            roi_day = (day_pnl / day_wagered) * 100 if day_wagered > 0 else 0
            print(f"  Mises du jour: {day_wagered:.2f}€ | P&L du jour: {day_pnl:+.2f}€ | ROI du jour: {roi_day:+.2f}%")

        total_pnl += day_pnl
        total_wagered += day_wagered
        current_date += timedelta(days=1)

    print("\n" + "=" * 40)
    print("RÉSULTATS COMPLETS DU BACKTEST")
    print("=" * 40)
    
    final_roi = (total_pnl / total_wagered) * 100 if total_wagered > 0 else 0
    
    print(f"Période analysée:          {start_date} à {end_date}")
    print(f"Nombre de jours avec paris:  {days_with_bets}")
    print(f"Total des mises engagées:    {total_wagered:.2f}€")
    print(f"Profit & Loss total:         {total_pnl:+.2f}€")
    print(f"ROI final:                   {final_roi:+.2f}%")
    print("=" * 40)


if __name__ == "__main__":
    main()
