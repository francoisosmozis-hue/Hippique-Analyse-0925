import argparse
import datetime as dt
import time
import requests
import re
from bs4 import BeautifulSoup
from typing import Set
from urllib.parse import urljoin

BASE_URL = "https://www.geny.com"

def fetch_urls_for_date(date: dt.date) -> Set[str]:
    """Fetches all race URLs for a specific date from Geny.com."""
    daily_url = f"{BASE_URL}/reunions-courses-pmu?date={date.strftime('%Y-%m-%d')}"
    urls: Set[str] = set()
    print(f"Fetching URLs for {date.strftime('%Y-%m-%d')} from {daily_url}")
    try:
        resp = requests.get(daily_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Trouver tous les liens "Partants/Stats/Prono" sans filtrer par pays
        for a_tag in soup.find_all("a", string=re.compile(r"Partants/Stats/Prono")):
            href = a_tag.get('href')
            if href:
                full_url = urljoin(BASE_URL, href)
                urls.add(full_url)
        
        print(f"  -> Found {len(urls)} race(s).")

    except requests.RequestException as e:
        print(f"Error fetching data for date {date}: {e}")
    return urls

def main():
    parser = argparse.ArgumentParser(description="Fetch historical Geny.com race URLs.")
    parser.add_argument("--days", type=int, default=7, help="Number of past days to fetch.")
    parser.add_argument("--output", type=str, default="urls_courses.txt", help="Output file path.")
    args = parser.parse_args()

    # Utiliser une date de référence passée valide
    ref_date = dt.date(2024, 5, 1)
    all_urls: Set[str] = set()

    print(f"Fetching all race URLs for the last {args.days} days (relative to {ref_date})...")
    for i in range(args.days):
        date_to_fetch = ref_date - dt.timedelta(days=i)
        urls_for_day = fetch_urls_for_date(date_to_fetch)
        if urls_for_day:
            all_urls.update(urls_for_day)
        time.sleep(1.5)

    if all_urls:
        sorted_urls = sorted(list(all_urls), reverse=True)
        with open(args.output, "w", encoding="utf-8") as f:
            for url in sorted_urls:
                f.write(f"{url}\n")
        print(f"\nSuccessfully wrote {len(all_urls)} URLs to {args.output}")
    else:
        print("\nNo URLs were found for the specified date range.")

if __name__ == "__main__":
    main()