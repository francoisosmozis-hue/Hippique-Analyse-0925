import json
import re
import sys
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_scraper.py <html_file>")
        sys.exit(1)

    file_path = sys.argv[1]
    with open(file_path, encoding='utf-8') as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")
    races_data = []
    reunion_tabs = soup.select("div.tab-pane[id^=r]")

    print(f"Found {len(reunion_tabs)} reunion tabs.")

    for tab in reunion_tabs:
        reunion_id = tab.get("id")
        reunion_label_element = tab.find_previous_sibling("a", {"data-bs-target": f"#{reunion_id}"})
        if reunion_label_element:
            reunion_name = reunion_label_element.get_text(strip=True)
        else:
            reunion_name = f"Réunion {reunion_id.upper()}"

        race_table = tab.find("table", class_="table")
        if not race_table:
            continue

        date_match = re.search(r'(\d{2}/\d{2}/\d{4})', soup.title.string if soup.title else '')
        race_date = date_match.group(1) if date_match else "N/A"

        for row in race_table.select("tbody tr"):
            race_info = {}
            try:
                # Get all cells, including th
                cols = row.find_all(['td', 'th'])
                if len(cols) < 4:
                    continue

                # RC Label
                rc_span = cols[1].find('span', class_='rxcx')
                if rc_span:
                    rc_text = rc_span.get_text(strip=True)
                    race_info["rc"] = rc_text
                    if ' ' in rc_text:
                        race_info["r_label"], race_info["c_label"] = rc_text.split(' ')
                    else: # fallback for R1C1 format
                        match = re.match(r"(R\d+)(C\d+)", rc_text)
                        if match:
                            race_info["r_label"], race_info["c_label"] = match.groups()


                # Time
                time_span = cols[0].find('span', class_='txt')
                if time_span:
                    race_info['start_time'] = time_span.get_text(strip=True)

                # Name and URL
                name_link = cols[2].find('a', class_='link')
                if name_link:
                    race_info['name'] = name_link.get_text(strip=True)
                    race_info['url'] = urljoin("https://www.boturfers.fr", name_link.get('href'))

                # Runners count
                runners_cell = cols[3]
                runners_text = runners_cell.get_text(strip=True)
                if runners_text.isdigit():
                    race_info['runners_count'] = int(runners_text)
                else:
                    race_info['runners_count'] = None


                race_info["reunion_name"] = reunion_name
                race_info["date"] = race_date

                races_data.append(race_info)
            except Exception as e:
                print(f"Error parsing row: {e}")
                print(row)

    print(f"Scraped {len(races_data)} races.")
    print(json.dumps(races_data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
