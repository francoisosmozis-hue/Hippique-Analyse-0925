import argparse
import json
import os
import re
import requests
from bs4 import BeautifulSoup

def parse_geny_race_page(html: str) -> tuple[dict, dict]:
    """Parses a Geny race page to extract runners and odds."""
    soup = BeautifulSoup(html, "html.parser")
    race_data = {"runners": []}
    odds_map = {}

    # Extraire les infos générales de la course
    info_course_tag = soup.find("span", class_="infoCourse")
    if info_course_tag:
        infos_text = info_course_tag.get_text(" ", strip=True)
        distance_match = re.search(r'(\d\s*\d{3})m', infos_text)
        if distance_match:
            race_data['distance'] = int(distance_match.group(1).replace(' ', ''))
        
        discipline_tag = info_course_tag.find("strong")
        if discipline_tag:
            race_data['discipline'] = discipline_tag.get_text(strip=True)

        allocation_match = re.search(r'([\d\s]+)€', infos_text)
        if allocation_match:
            race_data['allocation'] = int(allocation_match.group(1).replace(' ', ''))

    # Extraire les données des partants depuis la table principale
    partants_table = soup.find("table", id=re.compile(r"^dt_partants")) # id peut changer
    if not partants_table:
        partants_table = soup.find("div", id="dt_partants")
        
    if partants_table:
        tbody = partants_table.find("tbody", class_="yui-dt-data")
        if tbody:
            for row in tbody.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 12: continue
                
                num = cells[0].get_text(strip=True)
                nom = cells[1].get_text(strip=True)
                sexe_age_str = cells[3].get_text(strip=True)
                sexe, age = (sexe_age_str[0], int(sexe_age_str[1:])) if len(sexe_age_str) > 1 else ('', 0)
                musique = cells[8].get_text(strip=True)
                
                # Prendre la cote Genybet en priorité
                cote_str = cells[11].get_text(strip=True).replace(',', '.')
                if not cote_str:
                    cote_str = cells[10].get_text(strip=True).replace(',', '.') # Fallback sur cote PMU
                
                cote = float(cote_str) if cote_str and cote_str != '-' else None

                runner_info = {
                    "id": num, 
                    "num": num,
                    "name": nom,
                    "sexe": sexe,
                    "age": age,
                    "musique": musique,
                    "odds": cote
                }
                race_data["runners"].append(runner_info)
                if cote:
                    odds_map[num] = cote
    return race_data, odds_map

def main():
    parser = argparse.ArgumentParser(description="A simple scraper for a single Geny race page.")
    parser.add_argument("--url", required=True, help="The Geny.com race URL to scrape.")
    parser.add_argument("--outdir", required=True, help="Directory to save the output files.")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    
    print(f"  -> Scraping race data from {args.url}")
    try:
        resp = requests.get(args.url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        race_data, odds_map = parse_geny_race_page(resp.text)

        if not race_data.get("runners"):
            print(f"    -> Could not parse runners from page. The HTML structure may have changed.")
            # Sauvegarder le HTML pour le débogage
            with open(os.path.join(args.outdir, "failed_page.html"), "w", encoding="utf-8") as f:
                f.write(resp.text)
            return

        partants_file = os.path.join(args.outdir, "partants.json")
        with open(partants_file, "w", encoding="utf-8") as f:
            json.dump(race_data, f, ensure_ascii=False, indent=2)

        h5_odds_file = os.path.join(args.outdir, "h5_odds.json")
        with open(h5_odds_file, "w", encoding="utf-8") as f:
            json.dump(odds_map, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"  -> An error occurred during scraping: {e}")

if __name__ == "__main__":
    main()