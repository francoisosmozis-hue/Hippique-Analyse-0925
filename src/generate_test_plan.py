#!/usr/bin/env python3
"""
Script pour générer un plan.json de test
Usage: python scripts/generate_test_plan.py [--date YYYY-MM-DD] [--races N]
"""

import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

def generate_test_plan(date_str: str = None, num_races: int = 10) -> list:
    """
    Génère un plan de test avec des courses fictives
    
    Args:
        date_str: Date au format YYYY-MM-DD (défaut: aujourd'hui)
        num_races: Nombre de courses à générer
    
    Returns:
        Liste de courses
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    hippodromes = [
        "VINCENNES", "LONGCHAMP", "SAINT-CLOUD", "DEAUVILLE",
        "CHANTILLY", "MAISONS-LAFFITTE", "ENGHIEN", "AUTEUIL",
        "MARSEILLE-BORELY", "CAGNES-SUR-MER"
    ]
    
    plan = []
    base_time = datetime.strptime("13:30", "%H:%M")
    
    for i in range(num_races):
        # Répartir sur plusieurs réunions
        r_num = (i // 8) + 1
        c_num = (i % 8) + 1
        
        # Heure croissante (toutes les 25 minutes)
        race_time = base_time + timedelta(minutes=25 * i)
        time_str = race_time.strftime("%H:%M")
        
        # Hippodrome alterné
        meeting = hippodromes[i % len(hippodromes)]
        
        race = {
            "date": date_str,
            "r_label": f"R{r_num}",
            "c_label": f"C{c_num}",
            "meeting": meeting,
            "time_local": time_str,
            "course_url": f"https://www.zeturf.fr/fr/course/{date_str}/R{r_num}C{c_num}-{meeting.lower()}",
            "reunion_url": f"https://www.zeturf.fr/fr/reunion/{date_str}/R{r_num}"
        }
        
        plan.append(race)
    
    return plan

def main():
    parser = argparse.ArgumentParser(
        description="Génère un plan.json de test pour développement"
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Date au format YYYY-MM-DD (défaut: aujourd'hui)"
    )
    parser.add_argument(
        "--races",
        type=int,
        default=10,
        help="Nombre de courses à générer (défaut: 10)"
    )
    parser.add_argument(
        "--output",
        default="plan_test.json",
        help="Fichier de sortie (défaut: plan_test.json)"
    )
    
    args = parser.parse_args()
    
    print(f"🐴 Génération d'un plan de test...")
    print(f"   Date: {args.date or 'aujourd\'hui'}")
    print(f"   Courses: {args.races}")
    
    # Générer le plan
    plan = generate_test_plan(args.date, args.races)
    
    # Sauvegarder
    output_path = Path(args.output)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Plan généré: {output_path}")
    print(f"   {len(plan)} courses")
    print(f"   Premier départ: {plan[0]['time_local']}")
    print(f"   Dernier départ: {plan[-1]['time_local']}")
    
    # Afficher échantillon
    print("\n📋 Échantillon (3 premières courses):")
    for race in plan[:3]:
        print(f"   {race['r_label']}{race['c_label']} - {race['meeting']} - {race['time_local']}")
    
    print(f"\n💡 Utilisez ce fichier pour tester localement:")
    print(f"   1. Copier dans le conteneur Docker")
    print(f"   2. Ou utiliser en entrée de test")

if __name__ == "__main__":
    main()
