from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import date
from datetime import time as dt_time
from typing import Any

import requests
from bs4 import BeautifulSoup

from hippique_orchestrator.data_contract import (
    RaceData,
    RaceSnapshotNormalized,
    RunnerData,
    RunnerStats,
)
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.sources_interfaces import SourceProvider

logger = get_logger(__name__)

# Constants
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GPI/5.1; +https://example.local)"}
DEFAULT_TIMEOUT = 12.0
_DISCIPLINE_RE = re.compile(r"(trot|plat|obstacles?|mont[ée]|attelé)", re.IGNORECASE)
_TIME_RE = re.compile(r'(\d{1,2})h(\d{2})')
_SUSPICIOUS_HTML_PATTERNS = ("too many requests", "captcha", "access denied", "service unavailable")


class ZeturfProvider(SourceProvider):
    """Provides racing data from ZEturf (primarily race snapshots, used as fallback)."""

    name = "ZEturf"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

    async def fetch_programme(self, url: str, **kwargs) -> list[dict[str, Any]]:
        logger.warning("ZeturfProvider does not implement programme fetching.")
        return []

    async def fetch_snapshot(self, race_url: str, **kwargs) -> RaceSnapshotNormalized:
        logger.info(f"Début du scraping ZEturf: {race_url}")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._fetch_race_snapshot_sync, race_url)

    def _fetch_race_snapshot_sync(self, race_url: str) -> RaceSnapshotNormalized:
        try:
            html_content = self._http_get_sync(race_url)
            raw_snapshot_dict = self._parse_html(html_content, race_url)

            if not raw_snapshot_dict.get("runners"):
                raise ValueError("No runners found in snapshot data.")

            race_date_str = raw_snapshot_dict.get("date")
            race_date = date.fromisoformat(race_date_str) if race_date_str else date.today()

            rc_label = self._extract_rc_label_from_url(race_url) or f"R_C_{hash(race_url)}"

            start_time_local = None
            if start_time_str := raw_snapshot_dict.get("start_time"):
                if time_match := _TIME_RE.search(start_time_str):
                    hour, minute = int(time_match.group(1)), int(time_match.group(2))
                    start_time_local = dt_time(hour, minute)

            race_data = RaceData(
                date=race_date,
                rc_label=rc_label,
                discipline=raw_snapshot_dict.get("discipline"),
                start_time_local=start_time_local,
            )

            runners_data = [
                runner for raw_runner in raw_snapshot_dict.get("runners", [])
                if (runner := self._coerce_runner_entry(raw_runner)) is not None
            ]

            return RaceSnapshotNormalized(
                race=race_data,
                runners=runners_data,
                source_snapshot="Zeturf",
            )

        except Exception as e:
            logger.error(f"Failed to create RaceSnapshotNormalized for {race_url}: {e}", exc_info=True)
            return RaceSnapshotNormalized(
                race=RaceData(date=date.today(), rc_label="UNKNOWN_RC"),
                runners=[],
                source_snapshot="Zeturf_Failed",
            )

    def _extract_rc_label_from_url(self, url: str) -> str | None:
        match = re.search(r"/(R\d+C\d+)(?:-|$)", url, re.IGNORECASE)
        return match.group(1) if match else None

    def _http_get_sync(self, url: str) -> str:
        resp = self._session.get(url, timeout=DEFAULT_TIMEOUT)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} for {url}")
        text = resp.text
        if not text or any(p in text.lower() for p in _SUSPICIOUS_HTML_PATTERNS):
            raise RuntimeError(f"Payload suspect from {url}")
        return text

    def _parse_html(self, html: str, url: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")

        def _clean_text(value: str | None, lowercase: bool = False) -> str | None:
            if not value:
                return None
            text = unicodedata.normalize("NFKC", value).strip()
            return text.lower() if lowercase else text

        runners = []
        cotes_infos = {}
        script_tag = soup.find("script", string=re.compile("cotesInfos"))
        if script_tag:
            if cotes_match := re.search(r'cotesInfos:\s*(\{.*\})', script_tag.string):
                try:
                    cotes_infos = json.loads(cotes_match.group(1))
                except json.JSONDecodeError:
                    logger.warning(f"Failed to decode cotesInfos JSON for {url}")

        if cotes_infos:
            for num_key, data in cotes_infos.items():
                if not isinstance(data, dict) or not data.get("odds"):
                    continue

                # The horse number is the key, but we need to validate it's a number
                if not num_key.isdigit():
                    continue

                odds_data = data.get("odds", {})
                
                runner_data = {
                    "num": _clean_text(num_key),
                    # Name is not in cotesInfos, so we must parse the table or use a placeholder
                    "nom": f"Cheval {num_key}", 
                    "odds_win": odds_data.get("SG"),
                    "odds_place": None,
                }
                if "SPMin" in odds_data and "SPMax" in odds_data and odds_data["SPMin"] and odds_data["SPMax"]:
                    runner_data["odds_place"] = (odds_data["SPMin"] + odds_data["SPMax"]) / 2
                
                runners.append(runner_data)
        
        # Even if we get odds from script, we need names from the table.
        # This part will likely fail on JS-rendered pages, but we try anyway.
        partants_block = soup.find("div", id="block-partants")
        if partants_block:
            if table := partants_block.find("table", class_="table-data"):
                # Create a map of num -> name from the HTML table
                name_map = {}
                for row in table.select("tbody tr"):
                    num_cell = row.find("td", class_="numero")
                    name_cell = row.find("td", class_="cheval")
                    if num_cell and name_cell:
                        num = _clean_text(num_cell.get_text())
                        name = _clean_text(name_cell.get_text())
                        if num and name:
                            name_map[num] = name
                
                # Update runners with correct names
                for runner in runners:
                    if runner.get("num") in name_map:
                        runner["nom"] = name_map[runner["num"]]

        discipline_raw = None
        start_time_str = None
        if p_infos := soup.find("p", class_="infos"):
            infos_text = _clean_text(p_infos.get_text(), lowercase=True)
            discipline_raw = infos_text
            if time_match := _TIME_RE.search(infos_text):
                start_time_str = time_match.group(0)

        discipline_mapping = {
            "attelé": "Trot Attelé", "trot": "Trot Attelé", "monté": "Trot Monté",
            "plat": "Plat", "obstacles": "Obstacle", "haies": "Haies", "steeple": "Steeple-Chase",
        }
        discipline = next((v for k, v in discipline_mapping.items() if discipline_raw and k in discipline_raw), None)

        date_str = None
        if date_match := re.search(r"/(\d{4}-\d{2}-\d{2})/", url):
            date_str = date_match.group(1)

        return {"date": date_str, "discipline": discipline, "start_time": start_time_str, "runners": runners}

    def _parse_float_fr(self, value: Any) -> float | None:
        if value is None:
            return None

        s_value = str(value).strip()
        if not s_value or s_value == "-":
            return None

        # Replace comma with dot and remove non-breaking spaces
        s_value = s_value.replace(",", ".").replace("\xa0", "")

        try:
            return float(s_value)
        except (ValueError, TypeError):
            logger.debug(f"Could not convert '{value}' to float.")
            return None

    def _coerce_runner_entry(self, entry: Mapping[str, Any]) -> RunnerData | None:
        try:
            num = int(entry.get("num"))
        except (ValueError, TypeError):
            return None

        return RunnerData(
            num=num,
            nom=entry.get("nom", f"Runner {num}"),
            odds_win=self._parse_float_fr(entry.get("odds_win")),
            odds_place=self._parse_float_fr(entry.get("odds_place")),
        )

    async def fetch_stats_for_runner(self, runner_name: str, **kwargs) -> RunnerStats:
        logger.debug("ZeturfProvider does not fetch runner stats.")
        return RunnerStats()
