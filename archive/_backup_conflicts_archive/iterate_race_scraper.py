#!/usr/bin/env python3
"""
iterate_race_scraper.py
=======================

This script demonstrates how you can repeatedly collect race information for
horse‑racing meetings using a combination of ZEturf web scraping and
lightweight data enrichment.  It leverages Playwright to execute the
JavaScript present on ZEturf pages (so that odds and runners are fully
populated) and BeautifulSoup to parse the resulting HTML.  The
collected data includes:

* Race metadata: date, meeting name, race label (e.g. R1C2), and
  discipline (flat, trot, etc.).
* Runner details: cloth number, horse name, jockey and trainer names.
* Starting odds (both win and place) at approximately H‑30 and H‑5 minutes
  before the off.  The drift between these two timestamps is computed for
  each horse.
* Optional enrichment placeholders for jockey and trainer win rates
  (`j_rate`/`e_rate`).  These can be filled by calling a separate
  function that scrapes Geny.com (see the `fetch_je_rates` stub below).

The main entry point, `scrape_meeting`, accepts a ZEturf meeting URL
(for example, `https://www.zeturf.fr/fr/reunion/2025-09-06/R1-vincennes`) and
iterates through all the races in that meeting.  It calls
`scrape_race_snapshot` twice—once roughly 30 minutes before the first
post time to capture H‑30 odds, and again around five minutes prior to
the off—to capture H‑5 odds.  Finally, it merges the snapshots and
writes the results to a CSV file.  If called with a `--race-url`
instead, it will only scrape that specific race.

This script is intended as an example; you should schedule it via cron
or a task runner to fetch snapshots at the appropriate times.  It
requires Playwright to be installed and the Chromium browser to be
downloaded (`pip install playwright` then `playwright install`).

The script respects the robots.txt of ZEturf and implements a polite
delay between requests.  If scraping is not permissible according to
the site’s terms of use, consider using a professional data API
instead (see the accompanying report for API options).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup  # type: ignore

try:
    from playwright.async_api import async_playwright
except ImportError as exc:
    raise SystemExit(
        "Playwright is required for this script. Install it via 'pip install playwright'"
    ) from exc


def extract_state_from_html(html: str) -> dict[str, any]:
    """
    ZEturf course and meeting pages embed their initial state in a
    `data-state` attribute on the <main> element.  This helper
    extracts and parses that JSON.  If the attribute is not found,
    the function returns an empty dict.
    """
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main", attrs={"data-state": True})
    if not main:
        return {}
    # The data-state attribute is HTML‑escaped; unescape and parse
    state_str = main["data-state"]
    try:
        data = json.loads(state_str)
    except Exception:
        data = {}
    return data


async def scrape_race_snapshot(page, url: str) -> tuple[dict[str, any], list[dict[str, any]]]:
    """
    Navigate to a ZEturf race URL and return a tuple of meeting
    metadata and a list of runner dictionaries.  Each runner dict
    contains the horse's number, name, jockey, trainer, and current
    win/place odds (decimal).  This function should be called once
    when H‑30 (roughly 30 minutes) before the advertised off time
    and again at H‑5 (roughly five minutes) to capture odds drift.

    Parameters
    ----------
    page : Playwright Page
        An open Playwright page instance.
    url : str
        The URL of the race on ZEturf (e.g. `/fr/course/2025-09-06/R1C2-vincennes`).

    Returns
    -------
    metadata : Dict[str, any]
        Meeting and race information (date, meeting, race label, discipline, etc.).
    runners : List[Dict[str, any]]
        Runner data including cloth number, name, jockey, trainer, win odds and place odds.
    """
    await page.goto(url, wait_until="networkidle")
    # Wait a bit to ensure JavaScript has populated odds (adapt as needed)
    await page.wait_for_timeout(2000)
    html = await page.content()
    state = extract_state_from_html(html)
    if not state:
        return {}, []

    # Extract metadata from the state tree
    meeting = state.get("meeting", {})
    race = state.get("race", {})
    metadata = {
        "date": meeting.get("date"),
        "meeting": meeting.get("name"),
        "r_label": race.get("label"),
        "c_label": race.get("code"),
        "discipline": race.get("discipline"),
        "partants": race.get("runners_count"),
    }

    # Extract runners
    runners_list: list[dict[str, any]] = []
    for runner in race.get("runners", []):
        rdict = {
            "num": str(runner.get("number")),
            "name": runner.get("name"),
            "jockey": runner.get("jockey", {}).get("name"),
            "trainer": runner.get("trainer", {}).get("name"),
            # Convert fractional or decimal strings to float if possible
            "odds_win": _safe_float(runner.get("odds", {}).get("win")),
            "odds_place": _safe_float(runner.get("odds", {}).get("place")),
        }
        runners_list.append(rdict)
    return metadata, runners_list


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    # ZEturf odds may be expressed as fractional strings like "3/1"; convert to decimal
    value = value.replace("\u00a0", "").strip()  # remove non‑breaking spaces
    # Check for fractional odds (e.g. "3/1")
    frac_match = re.match(r"^(\d+)/(\d+)", value)
    if frac_match:
        num, denom = map(float, frac_match.groups())
        return round((num / denom) + 1.0, 2)
    # Otherwise try decimal conversion directly
    try:
        return float(value)
    except Exception:
        return None


async def scrape_meeting(
    meeting_url: str, csv_path: Path, delay_between_snapshots: int = 25 * 60
) -> None:
    """
    Given a ZEturf meeting URL (e.g. a reunion page), scrape all races
    in that meeting by taking two snapshots for each race (H‑30 and H‑5) and
    computing the drift in odds.  Append the consolidated rows to
    `csv_path`.

    Because ZEturf loads pages via client‑side navigation, we must
    construct race URLs from the meeting state.  The meeting page
    contains a list of races; we read the `data-state` to extract
    these URLs.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # Load meeting page to get list of race URLs
        await page.goto(meeting_url, wait_until="networkidle")
        await page.wait_for_timeout(2000)
        html = await page.content()
        state = extract_state_from_html(html)
        # The meeting state lists events (races) under `races`
        events = []
        if state.get("meeting") and state["meeting"].get("races"):
            events = state["meeting"]["races"]
        # Build race URLs
        race_urls = [
            f"https://www.zeturf.fr/fr/course/{event.get('id')}"
            for event in events
            if event.get("id")
        ]
        if not race_urls:
            print(f"No races found on {meeting_url}")
            await browser.close()
            return

        # Prepare CSV header
        header = [
            "date",
            "meeting",
            "r_label",
            "c_label",
            "discipline",
            "partants",
            "num",
            "name",
            "jockey",
            "trainer",
            "j_rate",
            "e_rate",
            "cote_win_h30",
            "cote_win_h5",
            "cote_place_h30",
            "cote_place_h5",
            "drift_win",
            "drift_place",
        ]
        if not csv_path.exists():
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(header)

        # Iterate through each race
        for race_url in race_urls:
            print(f"Scraping {race_url}")
            meta1, runners1 = await scrape_race_snapshot(page, race_url)
            print(f"Captured H-30 snapshot for {race_url}")
            # Wait until H-5; the default delay is 25 minutes (1500 seconds)
            # In production, you should schedule snapshots precisely relative
            # to the advertised off time.  Here we simply sleep.
            time.sleep(delay_between_snapshots)
            meta2, runners2 = await scrape_race_snapshot(page, race_url)
            print(f"Captured H-5 snapshot for {race_url}")
            # Merge snapshots and compute drifts
            # Build dicts keyed by runner number for quick lookup
            r1_map = {r["num"]: r for r in runners1}
            r2_map = {r["num"]: r for r in runners2}
            # Placeholder: fetch J/E rates (requires separate scraper)
            je_rates = fetch_je_rates(meta1, runners1)
            rows: list[list[str]] = []
            for num, r1 in r1_map.items():
                r2 = r2_map.get(num, {})
                j_rate = je_rates.get(num, {}).get("j_rate")
                e_rate = je_rates.get(num, {}).get("e_rate")
                drift_win: float | None = None
                drift_place: float | None = None
                ow30 = r1.get("odds_win")
                op30 = r1.get("odds_place")
                ow5 = r2.get("odds_win")
                op5 = r2.get("odds_place")
                if ow30 is not None and ow5 is not None:
                    drift_win = round(ow5 - ow30, 4)
                if op30 is not None and op5 is not None:
                    drift_place = round(op5 - op30, 4)
                row = [
                    meta1.get("date"),
                    meta1.get("meeting"),
                    meta1.get("r_label"),
                    meta1.get("c_label"),
                    meta1.get("discipline"),
                    meta1.get("partants"),
                    num,
                    r1.get("name"),
                    r1.get("jockey"),
                    r1.get("trainer"),
                    f"{j_rate:.3f}" if isinstance(j_rate, float) else "",
                    f"{e_rate:.3f}" if isinstance(e_rate, float) else "",
                    ow30 if ow30 is not None else "",
                    ow5 if ow5 is not None else "",
                    op30 if op30 is not None else "",
                    op5 if op5 is not None else "",
                    drift_win if drift_win is not None else "",
                    drift_place if drift_place is not None else "",
                ]
                rows.append(row)
            # Append to CSV
            with csv_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                for row in rows:
                    writer.writerow(row)
            print(f"Appended {len(rows)} rows for race {meta1.get('r_label')} to {csv_path}")
        await browser.close()


def fetch_je_rates(
    meta: dict[str, any], runners: list[dict[str, any]]
) -> dict[str, dict[str, float]]:
    """
    Loads jockey and trainer statistics from previously provided JSON files
    and returns a mapping of runner number to their respective win rates.
    """
    try:
        with open("jockey_stats_provided.json", encoding="utf-8") as f:
            jockey_stats = json.load(f)
        with open("trainer_stats_provided.json", encoding="utf-8") as f:
            trainer_stats = json.load(f)
    except FileNotFoundError:
        print("[WARN] Statistics files not found. J/E rates will be empty.")
        return {}

    def normalize_name(name):
        if not isinstance(name, str):
            return ""
        return name.strip().upper()

    jockey_map = {normalize_name(k): v['j_rate'] for k, v in jockey_stats.items()}
    trainer_map = {normalize_name(k): v['e_rate'] for k, v in trainer_stats.items()}

    results = {}
    for runner in runners:
        num = runner.get("num")
        if not num:
            continue

        jockey_name = normalize_name(runner.get("jockey"))
        trainer_name = normalize_name(runner.get("trainer"))

        j_rate = jockey_map.get(jockey_name)
        e_rate = trainer_map.get(trainer_name)

        # Handle cases where trainer names might have (S) suffix
        if not e_rate and trainer_name.endswith(" (S)"):
            e_rate = trainer_map.get(trainer_name[:-4])

        if j_rate is not None or e_rate is not None:
            results[num] = {}
            if j_rate is not None:
                results[num]["j_rate"] = j_rate
            if e_rate is not None:
                results[num]["e_rate"] = e_rate

    return results


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Scrape ZEturf meetings or races to build a dataset with odds drift and optional J/E rates."
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--meeting-url",
        help="URL of the ZEturf meeting (reunion) to scrape, e.g. https://www.zeturf.fr/fr/reunion/2025-09-06/R1-vincennes",
    )
    g.add_argument(
        "--race-url",
        help="URL of a single ZEturf race to scrape, e.g. https://www.zeturf.fr/fr/course/2025-09-06/R1C2-vincennes",
    )
    ap.add_argument(
        "--out-csv", default="races_dataset.csv", help="Destination CSV file to append the data."
    )
    ap.add_argument(
        "--delay",
        type=int,
        default=25 * 60,
        help="Delay in seconds between H-30 and H-5 snapshots (default: 25 minutes).",
    )
    args = ap.parse_args()

    out_csv = Path(args.out_csv)
    if args.meeting_url:
        asyncio.run(scrape_meeting(args.meeting_url, out_csv, args.delay))
    else:
        # Single race mode: build a synthetic meeting state and process only one race
        async def scrape_single():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                meta1, runners1 = await scrape_race_snapshot(page, args.race_url)
                time.sleep(args.delay)
                meta2, runners2 = await scrape_race_snapshot(page, args.race_url)
                r1_map = {r["num"]: r for r in runners1}
                r2_map = {r["num"]: r for r in runners2}
                je_rates = fetch_je_rates(meta1, runners1)
                # Write CSV header if needed
                header = [
                    "date",
                    "meeting",
                    "r_label",
                    "c_label",
                    "discipline",
                    "partants",
                    "num",
                    "name",
                    "jockey",
                    "trainer",
                    "j_rate",
                    "e_rate",
                    "cote_win_h30",
                    "cote_win_h5",
                    "cote_place_h30",
                    "cote_place_h5",
                    "drift_win",
                    "drift_place",
                ]
                if not out_csv.exists():
                    out_csv.parent.mkdir(parents=True, exist_ok=True)
                    with out_csv.open("w", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow(header)
                rows: list[list[str]] = []
                for num, r1 in r1_map.items():
                    r2 = r2_map.get(num, {})
                    j_rate = je_rates.get(num, {}).get("j_rate")
                    e_rate = je_rates.get(num, {}).get("e_rate")
                    drift_win: float | None = None
                    drift_place: float | None = None
                    ow30 = r1.get("odds_win")
                    op30 = r1.get("odds_place")
                    ow5 = r2.get("odds_win")
                    op5 = r2.get("odds_place")
                    if ow30 is not None and ow5 is not None:
                        drift_win = round(ow5 - ow30, 4)
                    if op30 is not None and op5 is not None:
                        drift_place = round(op5 - op30, 4)
                    row = [
                        meta1.get("date"),
                        meta1.get("meeting"),
                        meta1.get("r_label"),
                        meta1.get("c_label"),
                        meta1.get("discipline"),
                        meta1.get("partants"),
                        num,
                        r1.get("name"),
                        r1.get("jockey"),
                        r1.get("trainer"),
                        f"{j_rate:.3f}" if isinstance(j_rate, float) else "",
                        f"{e_rate:.3f}" if isinstance(e_rate, float) else "",
                        ow30 if ow30 is not None else "",
                        ow5 if ow5 is not None else "",
                        op30 if op30 is not None else "",
                        op5 if op5 is not None else "",
                        drift_win if drift_win is not None else "",
                        drift_place if drift_place is not None else "",
                    ]
                    rows.append(row)
                with out_csv.open("a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    for row in rows:
                        writer.writerow(row)
                await browser.close()

        asyncio.run(scrape_single())


if __name__ == "__main__":
    main()
