import requests
from bs4 import BeautifulSoup
import argparse
import json
from pathlib import Path


def scrape_geny_odds(course_id: str, output_path: Path):
    """
    Scrapes the odds for a given race from Geny.com and saves them to a JSON file.
    """
    url = f"https://www.geny.com/cotes?id_course={course_id}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # Use BeautifulSoup to parse the HTML content
        soup = BeautifulSoup(response.content, "html.parser")

        runners = []

        # Find the table containing the odds data
        table = soup.find("table", class_="tableau_partants")

        if not table:
            print("Could not find the odds table on the page.")
            return

        # Find all rows in the table body
        rows = table.find_all("tr")

        for row in rows:
            cols = row.find_all("td")
            # Ensure the row has enough columns and starts with a number
            if not cols or not cols[0].get_text(strip=True).isdigit():
                continue

            try:
                horse_num = cols[0].get_text(strip=True)
                horse_name = cols[1].get_text(strip=True)
                # The "Dernières cotes" is in the 5th column (index 4)
                odds_str = cols[4].get_text(strip=True).replace(",", ".")
                odds = float(odds_str)

                runners.append({"id": horse_num, "name": horse_name, "odds": odds})
            except (IndexError, ValueError) as e:
                # This will skip rows that don't have the expected structure
                # or odds that are not valid numbers.
                print(f"Skipping a row due to parsing error: {e}")
                continue

        output_data = {"runners": runners}

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        print(f"Successfully scraped odds for {len(runners)} runners to {output_path}")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while connecting to Geny.com: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape horse racing odds from Geny.com."
    )
    parser.add_argument(
        "--course-id", required=True, help="The ID of the race on Geny.com."
    )
    parser.add_argument("--output", required=True, help="Path to the output JSON file.")
    args = parser.parse_args()

    scrape_geny_odds(args.course_id, Path(args.output))
