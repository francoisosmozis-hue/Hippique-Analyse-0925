"""
Module for fetching statistics from various data sources.

Defines a common interface for stats providers and includes the implementation
for Zone-Turf.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from . import firestore_client

logger = logging.getLogger(__name__)

# ============================================
# Helper Functions
# ============================================


def _slugify(text: str) -> str:
    """Converts a string into a URL-friendly slug."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[àáâãäå]', 'a', text)
    text = re.sub(r'[èéêë]', 'e', text)
    text = re.sub(r'[ìíîï]', 'i', text)
    text = re.sub(r'[òóôõö]', 'o', text)
    text = re.sub(r'[ùúûü]', 'u', text)
    text = re.sub(r'[ç]', 'c', text)
    text = re.sub(r'[^a-z0-9\s-]', '', text).strip()
    text = re.sub(r'[\s-]+', '-', text)
    return text.strip('-')


# ============================================
# Data Models (as per user specification)
# ============================================


class JEStats(BaseModel):
    """Statistics for a Jockey or Trainer."""

    year: int
    starters: int = 0
    wins: int = 0
    places: int = 0
    win_rate: float | None = None
    place_rate: float | None = None


class Chrono(BaseModel):
    """Chrono/performance data for a horse."""

    record_attele_sec: float | None = None
    record_monte_sec: float | None = None
    last3_rk_sec: list[float] = Field(default_factory=list)
    rk_best3_sec: float | None = None


# ============================================
# Provider Interface
# ============================================


@runtime_checkable
class StatsProvider(Protocol):
    """
    Protocol defining the interface for a statistics provider.
    Ensures that any provider implements the required fetching methods.
    """

    def fetch_horse_chrono(self, horse_name: str, known_id: str | None) -> Chrono | None:
        """Fetches chrono data for a specific horse."""
        ...

    def fetch_jockey_stats(self, jockey_name: str, known_id: str | None) -> JEStats | None:
        """Fetches statistics for a specific jockey."""
        ...

    def fetch_trainer_stats(self, trainer_name: str, known_id: str | None) -> JEStats | None:
        """Fetches statistics for a specific trainer."""
        ...


# ============================================
# ZoneTurf Provider Implementation
# ============================================


class ZoneTurfProvider:
    """
    StatsProvider implementation for scraping data from Zone-Turf.
    """

    CACHE_COLLECTION = "zoneturf_id_cache"
    MAX_PAGES_TO_SCRAPE = 10  # Safety limit for pagination

    def __init__(self, config: dict, cache_ttl_days: int = 30):
        self.base_url = config.get("base_url", "https://www.zone-turf.fr")
        self.paths = {
            "horse": config.get("horse_path", "/cheval/{slug}-{id}/"),
            "jockey": config.get("jockey_path", "/jockey/{slug}-{id}/"),
            "trainer": config.get("trainer_path", "/entraineur/{slug}-{id}/"),
            "horse_letter_index": config.get(
                "horse_letter_index_path", "/cheval/lettre-{letter}.html?p={page}"
            ),
            "jockey_letter_index": config.get(
                "jockey_letter_index_path", "/jockey/lettre-{letter}.html?p={page}"
            ),
            "trainer_letter_index": config.get(
                "trainer_letter_index_path", "/entraineur/lettre-{letter}.html?p={page}"
            ),
        }
        self.cache_ttl = timedelta(days=cache_ttl_days)
        self.client = httpx.Client(base_url=self.base_url, follow_redirects=True)
        # Map entity types to their specific list selectors on index pages
        self.index_selectors = {
            "horse": "ul.list-chevaux > li > a",  # Corrected selector
            "jockey": "ul.list-jockeys > li > a",
            "trainer": "ul.list-entraineurs > li > a",
        }
        logger.info("ZoneTurfProvider initialized.")

    def _normalize_name(self, name: str) -> str:
        """Normalizes a name for consistent cache keys and comparisons."""
        if not name:
            return ""
        # Lowercase, remove accents, and keep only alphanumeric chars
        name = name.lower()
        name = re.sub(r'[àáâãäå]', 'a', name)
        name = re.sub(r'[èéêë]', 'e', name)
        name = re.sub(r'[ìíîï]', 'i', name)
        name = re.sub(r'[òóôõö]', 'o', name)
        name = re.sub(r'[ùúûü]', 'u', name)
        name = re.sub(r'[^a-z0-9]', '', name)
        return name

    def _get_id_from_cache(self, entity_type: str, name: str) -> str | None:
        """
        Retrieves a Zone-Turf ID from the Firestore cache if it exists and is not expired.
        """
        normalized_name = self._normalize_name(name)
        if not normalized_name:
            return None

        doc_id = f"{entity_type}_{normalized_name}"
        try:
            cached_doc = firestore_client.get_document(self.CACHE_COLLECTION, doc_id)
            if not cached_doc:
                return None

            cached_at = cached_doc.get("cached_at")
            if datetime.now(timezone.utc) - cached_at > self.cache_ttl:
                logger.info(f"Cache expired for {entity_type} '{name}'.")
                return None

            logger.debug(f"Cache hit for {entity_type} '{name}'.")
            return cached_doc.get("entity_id")
        except Exception as e:
            logger.error(f"Failed to read from cache for {doc_id}: {e}")
            return None

    def _set_id_to_cache(self, entity_type: str, name: str, entity_id: str):
        """
        Saves a resolved Zone-Turf ID to the Firestore cache.
        """
        normalized_name = self._normalize_name(name)
        if not normalized_name or not entity_id:
            return

        doc_id = f"{entity_type}_{normalized_name}"
        doc_data = {
            "entity_type": entity_type,
            "name": name,
            "normalized_name": normalized_name,
            "entity_id": entity_id,
            "cached_at": datetime.now(timezone.utc),
        }
        try:
            firestore_client.set_document(self.CACHE_COLLECTION, doc_id, doc_data)
            logger.info(f"Cached ID '{entity_id}' for {entity_type} '{name}'.")
        except Exception as e:
            logger.error(f"Failed to write to cache for {doc_id}: {e}")

    def _resolve_entity_id(self, entity_type: str, name: str) -> str | None:
        """
        Resolves an entity's name to its Zone-Turf ID.
        Uses cache first, then falls back to scraping the letter index pages.
        """
        if not name:
            return None

        # 1. Check cache
        cached_id = self._get_id_from_cache(entity_type, name)
        if cached_id:
            return cached_id

        logger.info(f"Cache miss for {entity_type} '{name}'. Resolving via scraping.")

        # 2. Scrape letter index
        index_path_template = self.paths.get(f"{entity_type}_letter_index")
        list_selector = self.index_selectors.get(entity_type)

        if not index_path_template or not list_selector:
            logger.error(f"No index path or selector defined for entity type '{entity_type}'.")
            return None

        first_letter = _slugify(name)[0]
        # Adjust for names that don't start with a letter
        if not 'a' <= first_letter <= 'z':
            first_letter = '0-9'

        target_name = name.lower()

        for page_num in range(1, self.MAX_PAGES_TO_SCRAPE + 1):
            index_path = index_path_template.format(letter=first_letter, page=page_num)
            try:
                response = self.client.get(index_path)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "lxml")

                links = soup.select(list_selector)
                if not links:
                    break  # No more links on this page, stop paginating

                for link in links:
                    if link.get_text(strip=True).lower() == target_name:
                        href = link.get("href")
                        match = re.search(r'-(\d+)/?$', href)
                        if match:
                            entity_id = match.group(1)
                            logger.info(f"Resolved ID for '{name}' to '{entity_id}'.")
                            self._set_id_to_cache(entity_type, name, entity_id)
                            return entity_id

            except httpx.HTTPStatusError as e:
                # 404 is acceptable if a page doesn't exist (e.g., page 2 for a letter)
                if e.response.status_code == 404:
                    logger.debug(
                        f"Page {page_num} not found for letter '{first_letter}', stopping pagination."
                    )
                    break
                logger.error(f"HTTP error while resolving ID for '{name}' at page {page_num}: {e}")
                break
            except Exception as e:
                logger.error(f"An error occurred while resolving ID for '{name}': {e}")
                return None

        logger.warning(f"Could not resolve ID for {entity_type} '{name}' after scraping.")
        return None

    def _parse_chrono_to_seconds(self, chrono_str: str | None) -> float | None:
        """Parses a chrono string like 1'11"6 or 59"8 into seconds."""
        if not chrono_str:
            return None

        try:
            # Standardize separators
            chrono_str = chrono_str.replace("''", '"').replace("'", '"')

            parts = chrono_str.split('"')

            if len(parts) == 3:  # Format M"S"T e.g., 1"11"6
                minutes = int(parts[0])
                seconds = int(parts[1])
                tenths = int(parts[2] or 0)  # Treat empty string as 0
                return minutes * 60 + seconds + tenths / 10.0
            elif len(parts) == 2:  # Format S"T e.g., 59"8
                seconds = int(parts[0])
                tenths = int(parts[1])
                return seconds + tenths / 10.0
            elif len(parts) == 1 and parts[0]:  # Can be a single number
                return float(parts[0])

        except (ValueError, IndexError):
            logger.warning(f"Could not parse chrono string: {chrono_str}")
            return None

        logger.warning(f"Unhandled chrono format: {chrono_str}")
        return None

    def fetch_horse_chrono(self, horse_name: str, known_id: str | None = None) -> Chrono | None:
        logger.debug(f"Fetching horse chrono for '{horse_name}' (ID: {known_id})")
        entity_id = known_id or self._resolve_entity_id("horse", horse_name)
        if not entity_id:
            return None

        slug = _slugify(horse_name)
        url_path = self.paths["horse"].format(slug=slug, id=entity_id)

        try:
            response = self.client.get(url_path)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            chrono_data = {}

            # 1. Parse records
            records_table = soup.find("table", class_="performances-table")
            if records_table:
                for row in records_table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) == 2:
                        label = cells[0].get_text(strip=True)
                        value = cells[1].get_text(strip=True)
                        if "Record attelé" in label:
                            chrono_data["record_attele_sec"] = self._parse_chrono_to_seconds(value)
                        elif "Record monté" in label:
                            chrono_data["record_monte_sec"] = self._parse_chrono_to_seconds(value)

            # 2. Parse last 3 chronos from performances
            last3_rk = []
            performances_table = soup.find("table", id="horse-performances-table")
            if performances_table:
                for row in performances_table.tbody.find_all("tr")[
                    :5
                ]:  # Check last 5 races for 3 valid chronos
                    if len(last3_rk) >= 3:
                        break
                    cells = row.find_all("td")
                    # Assuming chrono is in the 7th column (index 6)
                    if len(cells) > 6:
                        chrono_val = self._parse_chrono_to_seconds(cells[6].get_text(strip=True))
                        if chrono_val:
                            last3_rk.append(chrono_val)

            chrono_data["last3_rk_sec"] = last3_rk
            if last3_rk:
                chrono_data["rk_best3_sec"] = min(last3_rk)

            if not chrono_data:
                logger.warning(f"No chrono data found for horse '{horse_name}' at {url_path}")
                return None

            return Chrono(**chrono_data)

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error while fetching chrono for '{horse_name}': {e}")
            return None
        except Exception as e:
            logger.error(
                f"An error occurred while fetching chrono for '{horse_name}': {e}", exc_info=True
            )
            return None

    def fetch_jockey_stats(self, jockey_name: str, known_id: str | None = None) -> JEStats | None:
        logger.debug(f"Fetching jockey stats for '{jockey_name}' (ID: {known_id})")
        # For now, we assume ID resolution is not needed for jockeys, or a known_id is passed
        entity_id = known_id or self._resolve_entity_id("jockey", jockey_name)
        if not entity_id:
            return None

        slug = _slugify(jockey_name)
        url_path = self.paths["jockey"].format(slug=slug, id=entity_id)

        try:
            response = self.client.get(url_path)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            stats = {"year": datetime.now().year}

            # Find the stats table/section
            stats_header = soup.find("h2", string=re.compile(r"Statistiques \d{4} de"))
            if not stats_header:
                logger.warning(f"Stats section not found for jockey '{jockey_name}' at {url_path}")
                return None

            stats_table = stats_header.find_next_sibling("table")
            if not stats_table:
                logger.warning(f"Stats table not found for jockey '{jockey_name}' at {url_path}")
                return None

            # Extract stats from the table
            # This is highly dependent on the page structure
            for row in stats_table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) == 2:
                    label = cells[0].get_text(strip=True)
                    value_text = cells[1].get_text(strip=True)
                    try:
                        value = int(re.sub(r'\D', '', value_text))
                    except (ValueError, TypeError):
                        continue

                    if label == "Courses":
                        stats["starters"] = value
                    elif label == "Victoires":
                        stats["wins"] = value
                    elif label == "Placés":
                        stats["places"] = value

            if stats.get("starters", 0) > 0:
                stats["win_rate"] = stats.get("wins", 0) / stats["starters"]
                stats["place_rate"] = stats.get("places", 0) / stats["starters"]
            else:
                stats["win_rate"] = 0.0
                stats["place_rate"] = 0.0

            return JEStats(**stats)

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error while fetching stats for jockey '{jockey_name}': {e}")
            return None
        except Exception as e:
            logger.error(
                f"An error occurred while fetching stats for jockey '{jockey_name}': {e}",
                exc_info=True,
            )
            return None

    def fetch_trainer_stats(self, trainer_name: str, known_id: str | None = None) -> JEStats | None:
        logger.debug(f"Fetching trainer stats for '{trainer_name}' (ID: {known_id})")
        entity_id = known_id or self._resolve_entity_id("trainer", trainer_name)
        if not entity_id:
            return None

        slug = _slugify(trainer_name)
        url_path = self.paths["trainer"].format(slug=slug, id=entity_id)

        try:
            response = self.client.get(url_path)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            stats = {"year": datetime.now().year}

            stats_header = soup.find("h2", string=re.compile(r"Statistiques \d{4} de"))
            if not stats_header:
                logger.warning(
                    f"Stats section not found for trainer '{trainer_name}' at {url_path}"
                )
                return None

            stats_table = stats_header.find_next_sibling("table")
            if not stats_table:
                logger.warning(f"Stats table not found for trainer '{trainer_name}' at {url_path}")
                return None

            for row in stats_table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) == 2:
                    label = cells[0].get_text(strip=True)
                    value_text = cells[1].get_text(strip=True)
                    try:
                        value = int(re.sub(r'\D', '', value_text))
                    except (ValueError, TypeError):
                        continue

                    if label == "Partants":
                        stats["starters"] = value
                    elif label == "Victoires":
                        stats["wins"] = value
                    elif label == "Placés":
                        stats["places"] = value

            if stats.get("starters", 0) > 0:
                stats["win_rate"] = stats.get("wins", 0) / stats["starters"]
                stats["place_rate"] = stats.get("places", 0) / stats["starters"]
            else:
                stats["win_rate"] = 0.0
                stats["place_rate"] = 0.0

            return JEStats(**stats)

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error while fetching stats for trainer '{trainer_name}': {e}")
            return None
        except Exception as e:
            logger.error(
                f"An error occurred while fetching stats for trainer '{trainer_name}': {e}",
                exc_info=True,
            )
            return None


# Verify that the class implements the protocol at runtime (optional but good practice)
assert issubclass(ZoneTurfProvider, StatsProvider)
