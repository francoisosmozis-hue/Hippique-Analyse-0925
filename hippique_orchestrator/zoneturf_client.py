import bs4
import json
import re

def parse_html(html_content: str) -> bs4.BeautifulSoup:
    """Parses HTML content using BeautifulSoup."""
    return bs4.BeautifulSoup(html_content, "html5lib")

def parse_race_data(soup: bs4.BeautifulSoup) -> dict:

    """Parses race data from a ZEturf race page."""

    data = {}

    

    # Extract data from the cotesInfos JSON object

    cotes_infos = {}

    script_text = soup.find("script", string=re.compile("cotesInfos"))

    if script_text:

        match = re.search(r'cotesInfos: (\{.*\})', script_text.string)

        if match:

            cotes_json = match.group(1)

            # Fix for json loading by removing trailing comma

            cotes_json = re.sub(r',(\s*})', r'\1', cotes_json)

            cotes_infos = json.loads(cotes_json)



    runners = []

    table = soup.find("table", class_="table-runners")

    if not table:

        return {"runners": []}



    all_rows = table.find_all("tr")

    

    for row in all_rows:

        if not row.has_attr('data-runner'):

            continue

            

        runner = {}

        

        runner_number = row['data-runner']



        name_element = row.select_one(".cheval a.horse-name")

        if name_element:

            runner["name"] = name_element.text.strip()



        record_element = row.select_one("td.record b")

        if record_element:

            runner["record"] = record_element.text.strip()

        

        # Win/place rates are not on this page, will be handled later

        runner["win_rate"] = None

        runner["place_rate"] = None



        if runner_number in cotes_infos:

            odds_data = cotes_infos[runner_number].get("odds", {})

            runner["odds"] = odds_data.get("SG")

            runner["place_odds"] = odds_data.get("SPMin") # Using SPMin as a proxy for place_odds



        runners.append(runner)

    

    data["runners"] = runners

    return data

def calculate_quality_score(snapshot: dict) -> float:
    """
    Calculates a data quality score for the snapshot.
    The score is based on the completeness of the data for each runner.
    """
    if not snapshot or "runners" not in snapshot or not snapshot["runners"]:
        return 0.0

    total_runners = len(snapshot["runners"])
    valid_runners = 0
    
    # Adjusted to check for fields available in the main race page
    # win_rate and place_rate are expected to be on the horse details page
    required_keys = ["name", "record", "odds", "place_odds"]
    
    for runner in snapshot["runners"]:
        # Check that keys exist and that values are not None
        if all(key in runner and runner[key] is not None and runner[key] is not False for key in required_keys):
            valid_runners += 1
            
    return valid_runners / total_runners if total_runners > 0 else 0.0

def calculate_odds_place_ratio(snapshot: dict) -> float:
    """
    Calculates the ratio of runners where place_odds are available if odds are available.
    """
    if not snapshot or "runners" not in snapshot or not snapshot["runners"]:
        return 0.0
        
    runners_with_odds = 0
    runners_with_place_odds = 0
    
    for runner in snapshot["runners"]:
        if "odds" in runner and runner["odds"] is not None:
            runners_with_odds += 1
            if "place_odds" in runner and runner["place_odds"] is not None:
                runners_with_place_odds += 1
                
    return runners_with_place_odds / runners_with_odds if runners_with_odds > 0 else 1.0
