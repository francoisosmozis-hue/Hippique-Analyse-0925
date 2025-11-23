"""
Plan Builder UNIFIÉ - Combine 3 sources : PMU API, ZEturf, Geny

Architecture:
1. PMU API (priorité 1) : JSON structuré, données riches
2. ZEturf (priorité 2) : HTML, URLs officielles
3. Geny (priorité 3) : HTML, fallback heures

Usage:
    builder = UnifiedPlanBuilder()
    plan = builder.build_plan("2025-10-16", sources=["pmu", "zeturf", "geny"])
"""

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from config.config import config
from logging_utils import get_logger
from pmu_api_client import PMUClient
from time_utils import PARIS_TZ

logger = get_logger(__name__)


class UnifiedPlanBuilder:
    """
    Plan builder unifié avec fallback automatique entre sources
    """

    def __init__(self):
        self.pmu_client = PMUClient()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config.user_agent,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'fr-FR,fr;q=0.9',
        })
        self.last_source_used = None

    def build_plan(
        self,
        date_str: str,
        sources: list[str] | None = None,
        fill_missing_times: bool = True
    ) -> list[dict]:
        """
        Construit le plan en essayant plusieurs sources

        Args:
            date_str: "YYYY-MM-DD" ou "today"
            sources: Liste ordonnée de sources à essayer
                     ["pmu", "zeturf", "geny"] (défaut)
            fill_missing_times: Si True, compléter les heures manquantes

        Returns:
            Liste de courses avec structure standardisée
        """
        if date_str == "today":
            date_str = datetime.now(PARIS_TZ).strftime("%Y-%m-%d")

        if sources is None:
            # Ordre par défaut : PMU (JSON) > ZEturf (HTML) > Geny (HTML)
            sources = ["pmu", "zeturf", "geny"]

        logger.info(f"Building plan for {date_str} with sources: {sources}")

        plan = []

        # Essayer chaque source dans l'ordre
        for source in sources:
            try:
                if source == "pmu":
                    plan = self._build_from_pmu(date_str)
                elif source == "zeturf":
                    plan = self._build_from_zeturf(date_str)
                elif source == "geny":
                    plan = self._build_from_geny(date_str)
                else:
                    logger.warning(f"Unknown source: {source}")
                    continue

                if plan:
                    self.last_source_used = source
                    logger.info(f"✅ Plan built from {source}: {len(plan)} races")
                    break

            except Exception as e:
                logger.warning(f"Failed to build plan from {source}: {e}")
                continue

        # Compléter les heures manquantes si demandé
        if plan and fill_missing_times:
            plan = self._fill_missing_times(plan, date_str)

        # Déduplication et tri
        if plan:
            plan = self._deduplicate_and_sort(plan)

        logger.info(f"Final plan: {len(plan)} races from source '{self.last_source_used}'")
        return plan

    # ========================================================================
    # SOURCE 1 : PMU API (JSON - RECOMMANDÉ)
    # ========================================================================

    def _build_from_pmu(self, date_str: str) -> list[dict]:
        """
        Construit le plan depuis PMU API

        Avantages:
        - JSON structuré
        - Heures précises
        - Données riches (discipline, distance, etc.)
        """
        logger.info("Trying PMU API...")

        program = self.pmu_client.get_program(date_str)
        plan = self.pmu_client.to_plan(program, date_str)

        return plan

    # ========================================================================
    # SOURCE 2 : ZETURF (HTML)
    # ========================================================================

    def _build_from_zeturf(self, date_str: str) -> list[dict]:
        """
        Construit le plan depuis ZEturf

        Avantages:
        - URLs ZEturf directes
        - Source bookmaker officielle
        """
        logger.info("Trying ZEturf...")

        url = "https://www.zeturf.fr/fr/programmes-et-pronostics"

        time.sleep(config.RATE_LIMIT_DELAY)
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'lxml')
        races = []

        # Pattern URL: /fr/course/YYYY-MM-DD/RxCy-hippodrome
        course_links = soup.find_all('a', href=re.compile(r'/fr/course/\d{4}-\d{2}-\d{2}/R\d+C\d+'))

        logger.info(f"Found {len(course_links)} course links on ZEturf")

        for link in course_links:
            href = link.get('href')

            # Extraire date, R, C, slug
            match = re.search(
                r'/fr/course/(\d{4}-\d{2}-\d{2})/R(\d+)C(\d+)-(.+)',
                href
            )

            if not match:
                continue

            race_date, r_num, c_num, slug = match.groups()

            # Filtrer par date
            if race_date != date_str:
                continue

            # Extraire hippodrome
            meeting = self._extract_meeting_from_slug(slug)

            # Chercher heure
            time_local = self._extract_time_from_link_title(link)

            races.append({
                "date": race_date,
                "r_label": f"R{r_num}",
                "c_label": f"C{c_num}",
                "meeting": meeting.upper(),
                "time_local": time_local,
                "course_url": f"https://www.zeturf.fr{href}",
                "reunion_url": f"https://www.zeturf.fr/fr/reunion/{race_date}/R{r_num}"
            })

        return races

    def _extract_meeting_from_slug(self, slug: str) -> str:
        """Extrait le nom de l'hippodrome depuis le slug"""
        parts = slug.split('-')

        if len(parts) == 1:
            return parts[0].title()

        # Si le 2e mot n'est pas un keyword de course
        if len(parts) >= 2:
            first = parts[0].title()
            second = parts[1].lower()

            race_keywords = [
                'prix', 'premio', 'allowance', 'claiming', 'maiden',
                'handicap', 'stakes', 'conditions', 'listed', 'group'
            ]

            if second not in race_keywords:
                return f"{first} {second.title()}"

            return first

        return parts[0].title()

    def _extract_time_from_link_title(self, link_element) -> str | None:
        """Extrait l'heure depuis l'attribut 'title' du lien de la course."""
        title = link_element.get('title')
        if not title:
            return None

        # Cherche un format comme "13h55" ou "14:32"
        match = re.search(r'(\d{1,2})[h:](\d{2})', title)
        if match:
            hour, minute = match.groups()
            return f"{int(hour):02d}:{int(minute):02d}"

        return None

    # ========================================================================
    # SOURCE 3 : GENY (HTML - FALLBACK)
    # ========================================================================

    def _build_from_geny(self, date_str: str) -> list[dict]:
        """
        Construit le plan depuis Geny

        Avantages:
        - HTML simple
        - Heures explicites
        """
        logger.info("Trying Geny...")

        url = f"https://www.geny.com/reunions-courses-pmu/{date_str}"

        time.sleep(config.RATE_LIMIT_DELAY)
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'lxml')
        text = soup.get_text()

        races = []

        # Pattern: Hippodrome (R1)\nDébut des opérations vers 13:35\n1 - Prix...
        reunion_pattern = r'(.+?)\s+\(R(\d+)\).*?Début des opérations vers (\d{1,2}):(\d{2})'

        for match in re.finditer(reunion_pattern, text, re.DOTALL):
            hippodrome = match.group(1).strip()
            r_num = match.group(2)
            hour = match.group(3)
            minute = match.group(4)

            time_local = f"{int(hour):02d}:{int(minute):02d}"

            # Chercher les courses après ce match
            # Pattern: "1 - Prix...", "2 - Prix...", etc.
            course_section = text[match.end():match.end()+2000]
            course_pattern = r'(\d+)\s+-\s+(.+?)(?=\d+\s+-\s+|$)'

            for c_match in re.finditer(course_pattern, course_section):
                c_num = c_match.group(1)

                races.append({
                    "date": date_str,
                    "r_label": f"R{r_num}",
                    "c_label": f"C{c_num}",
                    "meeting": hippodrome.upper(),
                    "time_local": time_local,
                    "course_url": f"https://www.zeturf.fr/fr/course/{date_str}/R{r_num}C{c_num}",
                    "reunion_url": f"https://www.zeturf.fr/fr/reunion/{date_str}/R{r_num}"
                })

        return races

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _fill_missing_times(self, plan: list[dict], date_str: str) -> list[dict]:
        """
        Complète les heures manquantes en utilisant toutes les sources
        """
        # Compter les courses sans heure
        missing = sum(1 for r in plan if not r.get("time_local"))

        if missing == 0:
            return plan

        logger.info(f"Filling {missing} missing times...")

        # Essayer de récupérer les heures depuis Geny
        try:
            geny_times = self._get_times_from_geny(date_str)

            for race in plan:
                if not race.get("time_local"):
                    # Chercher par R label
                    time_found = geny_times.get(race["r_label"])
                    if time_found:
                        race["time_local"] = time_found
                        logger.debug(f"Filled time for {race['r_label']}{race['c_label']} from Geny")

        except Exception as e:
            logger.warning(f"Could not fill times from Geny: {e}")

        # Compter combien reste
        still_missing = sum(1 for r in plan if not r.get("time_local"))
        logger.info(f"After fill: {still_missing} still missing times")

        return plan

    def _get_times_from_geny(self, date_str: str) -> dict[str, str]:
        """
        Récupère uniquement les heures depuis Geny

        Returns:
            {"R1": "13:35", "R2": "15:00", ...}
        """
        url = f"https://www.geny.com/reunions-courses-pmu/{date_str}"

        time.sleep(config.RATE_LIMIT_DELAY)
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'lxml')
        text = soup.get_text()

        times = {}

        # Pattern: (R\d+) suivi de "Début...vers HH:MM"
        pattern = r'\(R(\d+)\).*?Début des opérations vers (\d{1,2}):(\d{2})'

        for match in re.finditer(pattern, text, re.DOTALL):
            r_num = match.group(1)
            hour = match.group(2)
            minute = match.group(3)

            times[f"R{r_num}"] = f"{int(hour):02d}:{int(minute):02d}"

        return times

    def _deduplicate_and_sort(self, plan: list[dict]) -> list[dict]:
        """Déduplique par (date, R, C) et tri par heure"""
        seen = set()
        unique = []

        for race in plan:
            key = (race["date"], race["r_label"], race["c_label"])
            if key not in seen:
                seen.add(key)
                unique.append(race)

        # Tri par heure
        def sort_key(r):
            if r.get("time_local"):
                try:
                    h, m = r["time_local"].split(':')
                    return (0, int(h), int(m))
                except Exception:
                    pass
            return (1, 99, 99)

        unique.sort(key=sort_key)
        return unique


# ============================================================================
# Test & Example
# ============================================================================

if __name__ == "__main__":
    import sys
    import json

    # Arguments
    date_str = sys.argv[1] if len(sys.argv) > 1 else "today"
    sources_arg = sys.argv[2] if len(sys.argv) > 2 else None
    sources = sources_arg.split(',') if sources_arg else ["pmu", "zeturf", "geny"]

    # Build
    builder = UnifiedPlanBuilder()
    plan = builder.build_plan(date_str, sources=sources)

    # Output JSON
    print(json.dumps(plan, indent=2))

