
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import pandas as pd
import numpy as np
import re
import requests
from bs4 import BeautifulSoup
from typing import Any, List, Dict
import datetime as dt
import time
import argparse

# Importer la logique de collecte de fetch_je_stats
from scripts.fetch_je_stats import collect_stats

def get_race_data_from_zeturf(url: str) -> Dict[str, Any]:
    """Fetches and parses the main data object from the ZEturf race page."""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        html = resp.text
        
        course_init_match = re.search(r"Course.init\\s*\\(\\s*(\\{.*?\\})\\s*\\);", html, re.DOTALL)
        if course_init_match:
            json_str = course_init_match.group(1)
            # Cette section de nettoyage peut nécessiter des ajustements si le format JSON de Zeturf change
            json_str = re.sub(r'([\\{,])\\s*(\\w+)\\s*:', r'\\1"\\2":', json_str)
            json_str = json_str.replace("'", '\"')
            
            course_data = json.loads(json_str)
            return course_data
    except (requests.RequestException, json.JSONDecodeError, AttributeError) as e:
        print(f"Error fetching or parsing ZEturf page {url}: {e}", file=sys.stderr)
    return {}

def get_arrival_from_api(date: str, reunion: int, course: int) -> List[int]:
    """Fetches the arrival from the open-pmu-api."""
    try:
        formatted_date = dt.datetime.strptime(date, "%Y-%m-%d").strftime("%d/%m/%Y")
        api_url = f"https://open-pmu-api.vercel.app/api/arrivees?date={formatted_date}"
        resp = requests.get(api_url, timeout=15)
        resp.raise_for_status()
        api_data = resp.json()
        
        for r in api_data.get('arrivees', []):
            if r.get('reunion') == reunion and r.get('course') == course:
                return r.get('arrivee', [])
    except (requests.RequestException, json.JSONDecodeError, AttributeError) as e:
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

def build_dataset_for_race(race_url: str) -> List[Dict[str, Any]]:
    """Builds a dataset for a single race URL, now including J/E stats and race data."""
    print(f"Processing {race_url}")
    race_data = get_race_data_from_zeturf(race_url)
    if not race_data:
        return []

    # Extraction des données de course
    reunion_date = race_data.get("reunionDate")
    discipline = race_data.get("discipline")
    distance = race_data.get("distance")
    allocation = race_data.get("allocation")
    num_runners = len(race_data.get("partants", []))
    course_id_match = re.search(r"_c(\d+)", race_url)
    geny_course_id = course_id_match.group(1) if course_id_match else None

    rc_match = re.search(r"(R\\d+C\\d+)", race_url)
    if not rc_match or not reunion_date or not geny_course_id:
        print("Could not extract key race identifiers from URL or data.", file=sys.stderr)
        return []
        
    reunion_num = int(re.search(r"R(\\d+)", rc_match.group(1)).group(1))
    course_num = int(re.search(r"C(\\d+)", rc_match.group(1)).group(1))

    # Récupération de l'arrivée
    arrival = get_arrival_from_api(reunion_date, reunion_num, course_num)
    if not arrival:
        print(f"Could not get arrival for R{reunion_num}C{course_num} on {reunion_date}. Skipping race.", file=sys.stderr)
        return []
    winner_number = arrival[0]

    # Récupération des stats J/E
    try:
        _, je_stats = collect_stats(geny_course_id, url=race_url.replace("zeturf.fr/fr/course", "geny.com/partants-pmu"))
    except Exception as e:
        print(f"Could not fetch J/E stats for course {geny_course_id}: {e}", file=sys.stderr)
        je_stats = {}

    cotes_infos = race_data.get("cotesInfos", {})
    all_horse_data = []
    
    for runner in race_data.get("partants", []):
        num_str = str(runner.get("numero"))
        if not num_str:
            continue
        
        num = int(num_str)
        
        horse_data = {
            "num": num,
            "name": runner.get("nom"),
            "gagnant": 1 if num == winner_number else 0,
            "age": runner.get("age"),
            "sexe": 1 if runner.get("sexe") == 'M' else 0,
        }
        horse_data.update(parse_musique(runner.get("musique")))

        # Ajout des cotes
        odds_info = cotes_infos.get(num_str, {}).get("odds", {})
        if odds_info and odds_info.get("SG") and float(odds_info.get("SG")) > 1:
            horse_data["cote"] = float(odds_info.get("SG"))
            horse_data["probabilite_implicite"] = 1 / float(odds_info.get("SG"))
        else:
            horse_data["cote"] = None
            horse_data["probabilite_implicite"] = 0

        # Ajout des nouvelles features
        runner_je_stats = je_stats.get(num_str, {})
        horse_data['j_win'] = runner_je_stats.get('j_win', 0)
        horse_data['e_win'] = runner_je_stats.get('e_win', 0)
        horse_data['distance'] = distance
        horse_data['allocation'] = allocation
        horse_data['num_runners'] = num_runners

        # One-hot encoding de la discipline
        disciplines = ['Plat', 'Trot Attelé', 'Haies', 'Cross', 'Steeple']
        for d in disciplines:
            horse_data[f'discipline_{d}'] = 1 if discipline == d else 0

        all_horse_data.append(horse_data)
        
    return all_horse_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a training dataset from a list of Zeturf race URLs.")
    parser.add_argument("url_file", help="Path to a file containing a list of Zeturf race URLs, one per line.")
    args = parser.parse_args()

    with open(args.url_file, "r") as f:
        race_urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    all_races_data = []
    for url in race_urls:
        try:
            race_data = build_dataset_for_race(url)
            if race_data:
                all_races_data.extend(race_data)
            time.sleep(1.5) # Be respectful to the server
        except Exception as e:
            print(f"An unexpected error occurred while processing {url}: {e}", file=sys.stderr)

    if all_races_data:
        df = pd.DataFrame(all_races_data)
        df.fillna(-1, inplace=True)
        
        output_path = os.path.join("data", "training_data.csv")
        df.to_csv(output_path, index=False)
        print(f"\nDataset successfully created at {output_path} with {len(df)} rows.")
        print("\n--- First 5 rows: ---")
        print(df.head())
    else:
        print("\nNo data was generated.")
