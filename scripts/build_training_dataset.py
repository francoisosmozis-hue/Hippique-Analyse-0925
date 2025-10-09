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

def get_race_data_from_zeturf(url: str) -> Dict[str, Any]:
    """Fetches and parses the main data object from the ZEturf race page."""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        html = resp.text
        
        course_init_match = re.search(r"Course.init\s*\(\s*(\{.*?\})\s*\);", html, re.DOTALL)
        if course_init_match:
            json_str = course_init_match.group(1)
            json_str = re.sub(r'([\\{,])\s*(\w+)\s*:', r'\1"\2":', json_str)
            json_str = json_str.replace("'", '"')
            
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
        resp = requests.get(api_url, timeout=10)
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
    """Builds a dataset for a single race URL."""
    print(f"Processing {race_url}")
    race_data = get_race_data_from_zeturf(race_url)
    if not race_data:
        return []

    reunion_date = race_data.get("reunionDate")
    rc_match = re.search(r"(R\d+C\d+)", race_url)
    if not rc_match:
        return []
    reunion_num = int(re.search(r"R(\d+)", rc_match.group(1)).group(1))
    course_num = int(re.search(r"C(\d+)", rc_match.group(1)).group(1))

    arrival = get_arrival_from_api(reunion_date, reunion_num, course_num)
    if not arrival:
        print(f"Could not get arrival for R{reunion_num}C{course_num} on {reunion_date}. Using fake arrival [1, 2, 3].")
        arrival = [1, 2, 3]
    winner_number = arrival[0]

    cotes_infos = race_data.get("cotesInfos", {})
    
    all_horse_data = []
    resp = requests.get(race_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")
    runner_rows = soup.select("tr[data-runner]")

    for row in runner_rows:
        num_str = row.get("data-runner")
        if not num_str:
            continue
        
        num = int(num_str)
        name_tag = row.select_one("a.horse-name")
        name = name_tag.get('title', '') if name_tag else ''
        musique_tag = row.select_one("td.musique")
        musique = musique_tag.get('title', '') if musique_tag else ''
        sexe_age_tag = row.select_one("td.sexe-age")
        sexe_age = sexe_age_tag.get_text(strip=True) if sexe_age_tag else ''
        sexe, age = ('M', 0)
        if sexe_age and '/' in sexe_age:
            sexe, age_str = sexe_age.split('/')
            try:
                age = int(age_str)
            except ValueError:
                age = 0

        horse_data = {
            "num": num,
            "name": name,
            "gagnant": 1 if num == winner_number else 0,
            "age": age,
            "sexe": 1 if sexe == 'M' else 0,
        }
        horse_data.update(parse_musique(musique))

        odds_info = cotes_infos.get(num_str, {}).get("odds", {})
        if odds_info and odds_info.get("SG"):
            horse_data["cote"] = odds_info.get("SG")
            horse_data["probabilite_implicite"] = 1 / odds_info.get("SG")
        else:
            horse_data["cote"] = None
            horse_data["probabilite_implicite"] = 0

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
        race_data = build_dataset_for_race(url)
        if race_data:
            all_races_data.extend(race_data)
        time.sleep(1) # Be respectful to the server

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