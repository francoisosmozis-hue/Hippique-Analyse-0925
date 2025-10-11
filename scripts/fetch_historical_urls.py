
import argparse
import datetime as dt
import time
import requests
import re
from bs4 import BeautifulSoup
from typing import Set, List
from urllib.parse import urljoin

BASE_URL = "https://www.geny.com"

def fetch_urls_for_date(date: dt.date) -> Set[str]:
    """Fetches all race URLs for a specific date from Geny.com."""
    daily_url = f"{BASE_URL}/reunions-courses-pmu?date={date.strftime('%Y-%m-%d')}"
    urls: Set[str] = set()
    print(f"Fetching ALL race URLs for {date.strftime('%Y-%m-%d')} from {daily_url}")
    try:
        resp = requests.get(daily_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Trouver tous les liens "Partants/Stats/Prono" sur la page, sans distinction
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
    parser = argparse.ArgumentParser(description="Fetch historical French Geny.com race URLs.")
    parser.add_argument("--date", help="A specific date to fetch (YYYY-MM-DD).")
    parser.add_argument("--start-date", help="Start date of a range to fetch (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="End date of a range to fetch (YYYY-MM-DD).")
    parser.add_argument("--days", type=int, help="Number of past days to fetch from today.")
    parser.add_argument("--output", type=str, default="urls_courses.txt", help="Output file path.")
    args = parser.parse_args()

    dates_to_fetch: List[dt.date] = []
    if args.date:
        try:
            dates_to_fetch.append(dt.datetime.strptime(args.date, "%Y-%m-%d").date())
        except ValueError:
            print(f"Error: Incorrect date format for --date. Please use YYYY-MM-DD.")
            return
    elif args.start_date and args.end_date:
        try:
            start = dt.datetime.strptime(args.start_date, "%Y-%m-%d").date()
            end = dt.datetime.strptime(args.end_date, "%Y-%m-%d").date()
            delta = end - start
            for i in range(delta.days + 1):
                dates_to_fetch.append(start + dt.timedelta(days=i))
        except ValueError:
            print(f"Error: Incorrect date format for --start-date or --end-date. Please use YYYY-MM-DD.")
            return
    else:
        days_to_fetch = args.days if args.days is not None else 7
        today = dt.date.today()
        for i in range(days_to_fetch):
            dates_to_fetch.append(today - dt.timedelta(days=i + 1))

    all_urls: Set[str] = set()
    print(f"Fetching URLs for {len(dates_to_fetch)} day(s)...")
    for date in dates_to_fetch:
        urls_for_day = fetch_urls_for_date(date)
        if urls_for_day:
            all_urls.update(urls_for_day)
        if len(dates_to_fetch) > 1:
            time.sleep(1.5)

    if all_urls:
        sorted_urls = sorted(list(all_urls), reverse=True)
        with open(args.output, "w", encoding="utf-8") as f:
            for url in sorted_urls:
                f.write(f"{url}\n")
        print(f"\nSuccessfully wrote {len(all_urls)} URLs to {args.output}")
    else:
        print("\nNo French URLs were found for the specified date(s).")

if __name__ == "__main__":
    main()
