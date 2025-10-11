import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import pandas as pd
import numpy as np
import re
import requests
from bs4 import BeautifulSoup
from typing import Any, List, Dict, Optional, Set
import datetime as dt
import time
import argparse

# La logique de collecte des stats J/E est maintenant dans ce même fichier pour plus de simplicité
from scripts.fetch_je_stats import collect_stats as fetch_je_stats_for_course

def get_arrival_from_api(date: str, reunion: int, course: int) -> List[int]:
    """Fetches the arrival from the open-pmu-api."""
    try:
        # L'API attend le format JJ-MM-AAAA
        formatted_date = dt.datetime.strptime(date, "%Y-%m-%d").strftime("%d-%m-%Y")
        api_url = f"https://open-pmu-api.vercel.app/api/arrivees?date={formatted_date}"
        resp = requests.get(api_url, timeout=15)
        resp.raise_for_status()
        api_data = resp.json()
        
        for r in api_data.get('arrivees', []):
            if r.get('reunion') == reunion and r.get('course') == course:
                # L'API retourne une liste de strings, on les convertit en int
                return [int(x) for x in r.get('arrivee', []) if x.isdigit()]
    except (requests.RequestException, json.JSONDecodeError, AttributeError, KeyError) as e:
        print(f"Error fetching arrival from API for R{reunion}C{course} on {date}: {e}", file=sys.stderr)
    return []

def parse_musique(musique_str: str) -> dict:
    if not isinstance(musique_str, str):
        return {}
    musique_recente = re.sub(r'\\(.*\\)', '', musique_str)
    performances = re.findall(r'(\\d+|[A-Z])', musique_recente)
    last_5 = performances[:5]
    return {
        'musique_victoires_5_derniers': last_5.count('1'),
        'musique_places_5_derniers': sum(1 for p in last_5 if p in ['1', '2', '3']),
        'musique_disqualifications_5_derniers': sum(1 for p in last_5 if p in ['D', 'A', 'T', 'R']),
        'musique_position_moyenne_5_derniers': np.mean([int(p) for p in last_5 if p.isdigit()] or [-1]),
    }

def parse_geny_race_page(html: str) -> Dict[str, Any]:
    """Parses the HTML of a Geny race page to extract all relevant data."""
    soup = BeautifulSoup(html, "html.parser")
    race_data = {"partants": []}

    # Extraire les infos générales de la course
    info_course_tag = soup.find("div", class_="infoCourse")
    if info_course_tag:
        infos_text = info_course_tag.get_text(" ", strip=True)
        distance_match = re.search(r'(\\d\\s*\\d{3})\\s*m', infos_text)
        if distance_match:
            race_data['distance'] = int(distance_match.group(1).replace(' ', ''))
        
        discipline_tag = info_course_tag.find("strong")
        if discipline_tag:
            race_data['discipline'] = discipline_tag.get_text(strip=True)

        allocation_match = re.search(r'Allocation\\s*:\s*([\\d\\s]+)€', infos_text)
        if allocation_match:
            race_data['allocation'] = int(allocation_match.group(1).replace(' ', ''))

    # Extraire les données des partants
    partants_table = soup.find("table", id="partants")
    if partants_table:
        for row in partants_table.find("tbody").find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 5: continue
            
            num = cells[0].get_text(strip=True)
            nom = cells[2].find("a").get_text(strip=True) if cells[2].find("a") else ''
            sexe_age_str = cells[3].get_text(strip=True)
            sexe, age = (sexe_age_str[0], int(sexe_age_str[1:])) if len(sexe_age_str) > 1 else ('', 0)
            musique = cells[10].get_text(strip=True) if len(cells) > 10 else ''
            
            # La cote est souvent dans une cellule avec une classe comme 'rapport'
            cote_tag = cells[5].find("strong")
            cote = float(cote_tag.get_text(strip=True).replace(',', '.')) if cote_tag else None

            race_data["partants"].append({
                "num": num,
                "nom": nom,
                "sexe": sexe,
                "age": age,
                "musique": musique,
                "cote": cote
            })
    return race_data

def build_dataset_for_race(race_url: str) -> List[Dict[str, Any]]:
    """Builds a dataset for a single Geny race URL."""
    print(f"Processing {race_url}")
    try:
        resp = requests.get(race_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except requests.RequestException as e:
        print(f"Could not fetch {race_url}: {e}", file=sys.stderr)
        return []

    # Extraire les données de la page Geny
    race_data = parse_geny_race_page(html)
    if not race_data or not race_data.get("partants"):
        print(f"Could not parse race data from {race_url}", file=sys.stderr)
        return []

    # Extraire les identifiants de la course depuis l'URL
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', race_url)
    reunion_course_match = re.search(r'_c(\d+)', race_url)
    geny_course_id = reunion_course_match.group(1) if reunion_course_match else None
    
    # Pour l'API des arrivées, il faut R et C
    # On ne peut pas les déduire de manière fiable de l'URL Geny, on saute cette étape pour l'instant
    # On utilisera une arrivée factice pour la construction du dataset
    # winner_number = 1 # A remplacer par une vraie logique si possible

    # Récupération des stats J/E
    try:
        _, je_stats = fetch_je_stats_for_course(geny_course_id, url=race_url)
    except Exception as e:
        print(f"Could not fetch J/E stats for course {geny_course_id}: {e}", file=sys.stderr)
        je_stats = {}

    all_horse_data = []
    num_runners = len(race_data.get("partants", []))

    for runner in race_data["partants"]:
        num_str = str(runner.get("num"))
        if not num_str:
            continue
        
        horse_data = {
            "date": reunion_date,
            "reunion_num": reunion_num,
            "course_num": course_num,
            "num": runner.get("num"),
            "name": runner.get("nom"),
            # La colonne 'gagnant' est mise à 0 par défaut et sera corrigée par populate_winners.py
            "gagnant": 0,
            "age": runner.get("age"),
            "sexe": 1 if runner.get("sexe") == 'M' else 0,
        }
        horse_data.update(parse_musique(runner.get("musique")))

        if runner.get("cote") and runner.get("cote") > 1:
            horse_data["cote"] = runner.get("cote")
            horse_data["probabilite_implicite"] = 1 / runner.get("cote")
        else:
            horse_data["cote"] = None
            horse_data["probabilite_implicite"] = 0

        runner_je_stats = je_stats.get(num_str, {})
        horse_data['j_win'] = runner_je_stats.get('j_win', 0)
        horse_data['e_win'] = runner_je_stats.get('e_win', 0)
        horse_data['distance'] = race_data.get('distance')
        horse_data['allocation'] = race_data.get('allocation')
        horse_data['num_runners'] = num_runners

        disciplines = ['Plat', 'Trot Attelé', 'Haies', 'Cross', 'Steeple']
        for d in disciplines:
            horse_data[f'discipline_{d}'] = 1 if race_data.get('discipline') == d else 0

        all_horse_data.append(horse_data)
        
    return all_horse_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a training dataset from a list of Geny.com race URLs.")
    parser.add_argument("url_file", help="Path to a file containing a list of Geny.com race URLs, one per line.")
    args = parser.parse_args()

    with open(args.url_file, "r") as f:
        race_urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    all_races_data = []
    for url in race_urls:
        try:
            race_data = build_dataset_for_race(url)
            if race_data:
                all_races_data.extend(race_data)
            time.sleep(1.5)
        except Exception as e:
            print(f"An unexpected error occurred while processing {url}: {e}", file=sys.stderr)

    if all_races_data:
        df = pd.DataFrame(all_races_data)
        df.fillna(-1, inplace=True)
        
        output_path = os.path.join("data", "training_data.csv")
        df.to_csv(output_path, index=False)
        print(f"\nDataset successfully created at {output_path} with {len(df)} rows.")
        print("Please note: The 'gagnant' column is not populated and needs to be filled in separately using official results.")
        print("\n--- First 5 rows: ---")
        print(df.head())
    else:
        print("\nNo data was generated.")