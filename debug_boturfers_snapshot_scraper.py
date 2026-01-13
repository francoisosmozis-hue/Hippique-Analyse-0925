import json
import re
import sys
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


# Mimic the structure of BoturfersProvider for debugging
class MockBoturfersProvider:
    def __init__(self):
        self.base_url = "https://www.boturfers.fr"

    def _parse_race_details_page(self, soup: BeautifulSoup, race_url: str) -> dict[str, Any]:
        metadata = self._parse_race_metadata(soup, race_url)
        runners_data = self._parse_race_runners_from_details_page(soup)
        return {**metadata, "runners": runners_data, "source": "Boturfers", "ts_fetch": datetime.now().isoformat()}

    def _parse_race_metadata(self, soup: BeautifulSoup, race_url: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        h1_tag = soup.find("h1", class_="my-3")
        if h1_tag:
            metadata["race_name"] = h1_tag.get_text(strip=True)

        rc_match = re.search(r"/(R\d+C\d+)-", race_url)
        if rc_match:
            metadata["rc_label"] = rc_match.group(1)
            metadata["r_label"] = rc_match.group(1).split('C')[0]
            metadata["c_label"] = rc_match.group(1).split('C')[1]

        date_match = re.search(r'courses/(\d{4}-\d{2}-\d{2})', race_url)
        if date_match:
            metadata["date"] = date_match.group(1)

        info_block = soup.find("div", class_="card-body text-center mb-3")
        if info_block:
            metadata_text = info_block.get_text(strip=True).replace("\n", " ")

            discipline_match = re.search(r"(Trot|Plat|Obstacle|Steeple|Haies|Cross)", metadata_text, re.IGNORECASE)
            if discipline_match:
                metadata["discipline"] = discipline_match.group(1)

            distance_match = re.search(r"(\d{3,4})\s*mètres", metadata_text)
            if distance_match:
                metadata["distance"] = int(distance_match.group(1))

            prize_match = re.search(r"(\d{1,3}(?:\s?\d{3})*)\s*euros", metadata_text, re.IGNORECASE)
            if prize_match:
                metadata["prize"] = int(prize_match.group(1).replace(" ", ""))

            conditions_tag = info_block.find("p", class_="card-text")
            if conditions_tag:
                conditions_text = conditions_tag.get_text(strip=True)
                type_match = re.search(r"(Attelé|Monté|Plat|Obstacle)", conditions_text, re.IGNORECASE)
                if type_match:
                    metadata["course_type"] = type_match.group(1)

                corde_match = re.search(r"corde (à gauche|à droite)", conditions_text, re.IGNORECASE)
                if corde_match:
                    metadata["corde"] = "Gauche" if "gauche" in corde_match.group(1) else "Droite"
                else:
                    metadata["corde"] = "N/A"
            else:
                metadata["corde"] = "N/A"
        return metadata

    def _parse_race_runners_from_details_page(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        runners_data = []
        # Corrected selector: find the div with id="partants" and then the table within it
        partants_div = soup.find("div", id="partants")
        if not partants_div:
            print("WARNING: Could not find 'div' with id 'partants'.")
            return []

        runners_table = partants_div.find("table", class_="table")
        if not runners_table:
            print("WARNING: Could not find 'table' with class 'table' within 'div#partants'.")
            return []

        for row in runners_table.select("tbody tr"):
            runner_info: dict[str, Any] = {}
            try:
                cols = row.find_all("td")
                if len(cols) < 7:
                    print(f"WARNING: Incomplete runner row: {row.get_text()}. Skipping.")
                    continue

                num_span = cols[0].find("span", class_="num-partant")
                runner_info["num"] = int(num_span.get_text(strip=True)) if num_span else None

                name_link = cols[1].find("a")
                runner_info["name"] = name_link.get_text(strip=True) if name_link else ""
                runner_info["horse_url"] = urljoin(self.base_url, name_link['href']) if name_link and 'href' in name_link.attrs else ""

                jockey_link = cols[2].find("a")
                runner_info["jockey"] = jockey_link.get_text(strip=True) if jockey_link else ""

                trainer_link = cols[3].find("a")
                runner_info["trainer"] = trainer_link.get_text(strip=True) if trainer_link else ""

                musique_span = cols[4]
                musique_text = musique_span.get_text(strip=True) if musique_span else ""
                runner_info["musique"] = musique_text

                gains_span = cols[5]
                gains_text = gains_span.get_text(strip=True).replace(" ", "").replace("\xa0", "")
                runner_info["gains"] = float(gains_text) if gains_text.replace('.', '', 1).isdigit() else None

                cote_span = cols[6].find("span", class_="cote")
                cote_text = cote_span.get_text(strip=True).replace(",", ".") if cote_span else None
                runner_info["odds_win"] = float(cote_text) if cote_text and cote_text.replace('.', '', 1).isdigit() else None

                runner_info["odds_place"] = None

                runners_data.append(runner_info)
            except Exception as e:
                print(f"WARNING: Failed to parse a runner row: {e}. Row skipped. HTML: {row}")
        return runners_data


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_boturfers_snapshot_scraper.py <html_file> <race_url>")
        sys.exit(1)

    html_file_path = sys.argv[1]
    race_url = sys.argv[2]

    with open(html_file_path, encoding='utf-8') as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    mock_provider = MockBoturfersProvider()
    snapshot = mock_provider._parse_race_details_page(soup, race_url)

    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    if snapshot and snapshot.get("runners"):
        print(f"SUCCESS: Scraped {len(snapshot['runners'])} runners.")
    else:
        print("FAILURE: No snapshot data or runners found.")

if __name__ == "__main__":
    main()
