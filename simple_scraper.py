
import requests
import re
import json
import sys
from bs4 import BeautifulSoup

def scrape_zeturf_course(url: str):
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        html = resp.text

        course_init_match = re.search(r"Course\.init\s*\(\s*(\{.*?\})\s*\);", html, re.DOTALL)
        if not course_init_match:
            print("Error: Could not find Course.init object in the page.", file=sys.stderr)
            return

        json_str = course_init_match.group(1)
        json_str = re.sub(r'([\{,])\s*(\w+)\s*:', r'\1"\2":', json_str)
        json_str = json_str.replace("'", '"')

        course_data = json.loads(json_str)
        
        runners = []
        cotes_infos = course_data.get("cotesInfos", {})
        soup = BeautifulSoup(html, "html.parser")
        runner_rows = soup.select("tr[data-runner]")

        for row in runner_rows:
            num = row.get("data-runner")
            if not num:
                continue

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

            runner_data = {
                "num": num,
                "name": name,
                "musique": musique,
                "sexe": sexe,
                "age": age,
            }

            odds_info = cotes_infos.get(num, {}).get("odds", {})
            if odds_info:
                runner_data["cote"] = odds_info.get("SG")
                runner_data["odds_place"] = odds_info.get("SPMin")

            runners.append(runner_data)

        result = {
            "course_id": course_data.get("courseId"),
            "reunion_id": course_data.get("reunionId"),
            "nom_reunion": course_data.get("nomReunion"),
            "date": course_data.get("reunionDate"),
            "runners": runners
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python simple_scraper.py <url>", file=sys.stderr)
        sys.exit(1)
    
    scrape_zeturf_course(sys.argv[1])
