
import argparse
import datetime as dt
import time
import requests
import re
from bs4 import BeautifulSoup
from typing import List, Set

BASE_URL = "https://www.zeturf.fr"

def fetch_urls_for_date(date: dt.date) -> Set[str]:
    """Fetches all race URLs for a specific date from the ZEturf archives."""
    archive_url = f"{BASE_URL}/fr/courses/archives/{date.strftime('%Y-%m-%d')}"
    urls: Set[str] = set()
    print(f"Fetching URLs for {date.strftime('%Y-%m-%d')} from {archive_url}")
    try:
        resp = requests.get(archive_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Find all links pointing to a race page
        for a_tag in soup.find_all("a", href=True):
            href = a_tag['href']
            if href and re.match(r"/fr/course/\\d{4}-\\d{2}-\\d{2}/R\\d+C\\d+", href):
                # Reconstituer l'URL absolue
                if not href.startswith("http"):
                    full_url = f"{BASE_URL}{href}"
                else:
                    full_url = href
                urls.add(full_url)
    except requests.RequestException as e:
        print(f"Error fetching data for date {date}: {e}")
    return urls

def main():
    parser = argparse.ArgumentParser(description="Fetch historical ZEturf race URLs.")
    parser.add_argument("--days", type=int, default=7, help="Number of past days to fetch.")
    parser.add_argument("--output", type=str, default="urls_courses.txt", help="Output file path.")
    args = parser.parse_args()

    today = dt.date.today()
    all_urls: Set[str] = set()

    print(f"Fetching race URLs for the last {args.days} days...")
    for i in range(args.days):
        # On commence par hier
        date_to_fetch = today - dt.timedelta(days=i + 1)
        urls_for_day = fetch_urls_for_date(date_to_fetch)
        if urls_for_day:
            all_urls.update(urls_for_day)
        # Être respectueux envers le serveur
        time.sleep(1.5)

    if all_urls:
        # Trier les URLs pour un ordre cohérent
        sorted_urls = sorted(list(all_urls), reverse=True)
        with open(args.output, "w", encoding="utf-8") as f:
            for url in sorted_urls:
                f.write(f"{url}\n")
        print(f"\nSuccessfully wrote {len(all_urls)} URLs to {args.output}")
    else:
        print("\nNo URLs were found for the specified date range.")

if __name__ == "__main__":
    main()
