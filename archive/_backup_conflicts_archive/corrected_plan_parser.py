"""
Plan Builder - VERSION CORRIGÉE basée sur structure HTML réelle ZEturf
Testé sur https://www.zeturf.fr/fr/programmes-et-pronostics
"""

import re
import time

import requests
from bs4 import BeautifulSoup

from .config import config
from .logging_utils import logger
from .time_utils import now_paris


class PlanBuilder:
    """Construit le plan du jour depuis ZEturf (structure HTML vérifiée)"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config.USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'fr-FR,fr;q=0.9',
        })

    def build_plan(self, date_str: str) -> list[dict]:
        """
        Construit le plan complet pour une date

        Args:
            date_str: "YYYY-MM-DD" ou "today"

        Returns:
            Liste de courses avec structure:
            {
                "date": "YYYY-MM-DD",
                "r_label": "R1",
                "c_label": "C3",
                "meeting": "VINCENNES",
                "time_local": "14:15",
                "course_url": "https://www.zeturf.fr/fr/course/...",
                "reunion_url": "https://www.zeturf.fr/fr/reunion/..."
            }
        """
        if date_str == "today":
            date_str = now_paris().strftime("%Y-%m-%d")

        logger.info(f"Building plan for date {date_str}")

        # Étape 1: Parser ZEturf pour URLs et structure R/C
        zeturf_plan = self._parse_zeturf_program(date_str)

        if not zeturf_plan:
            logger.warning("No races found on ZEturf")
            return []

        # Étape 2: Déduplication et tri
        plan = self._deduplicate_and_sort(zeturf_plan)

        logger.info(f"Plan built: {len(plan)} races")
        return plan

    def _parse_zeturf_program(self, date_str: str) -> list[dict]:
        """
        Parse la page 'Programmes et pronostics' ZEturf

        Structure HTML vérifiée (oct 2025):
        <a href="/fr/course/2025-10-16/R1C1-hippodrome-nom">...</a>

        Le texte contient l'heure au format "XXhYY" avant le lien
        """
        # URL principale du programme
        url = "https://www.zeturf.fr/fr/programmes-et-pronostics"

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'lxml')
            races = []

            # Pattern URL vérifié: /fr/course/YYYY-MM-DD/RxCy-...
            # IMPORTANT: Chercher tous les liens <a> avec href contenant /fr/course/
            course_links = soup.find_all('a', href=re.compile(r'/fr/course/\d{4}-\d{2}-\d{2}/R\d+C\d+'))

            logger.info(f"Found {len(course_links)} course links on ZEturf")

            for link in course_links:
                href = link.get('href')

                # Extraire date, R, C depuis l'URL
                # Format: /fr/course/2025-10-16/R7C4-concepcion-premio
                match = re.search(
                    r'/fr/course/(\d{4}-\d{2}-\d{2})/R(\d+)C(\d+)-(.+)',
                    href
                )

                if not match:
                    continue

                race_date, r_num, c_num, slug = match.groups()

                # Filtrer par date demandée
                if race_date != date_str:
                    continue

                # Extraire meeting depuis le slug
                meeting = self._extract_meeting_from_slug(slug)

                # Chercher l'heure dans le texte autour du lien
                time_local = self._extract_time_near_link(link)

                race = {
                    "date": race_date,
                    "r_label": f"R{r_num}",
                    "c_label": f"C{c_num}",
                    "meeting": meeting.upper(),
                    "time_local": time_local,
                    "course_url": f"https://www.zeturf.fr{href}",
                    "reunion_url": f"https://www.zeturf.fr/fr/reunion/{race_date}/R{r_num}"
                }

                races.append(race)

            logger.info(f"Parsed {len(races)} races for {date_str} from ZEturf")
            return races

        except Exception as e:
            logger.error(f"Error parsing ZEturf: {e}", exc_info=True)
            return []

    def _extract_meeting_from_slug(self, slug: str) -> str:
        """
        Extrait le nom de l'hippodrome depuis le slug

        Exemples:
        - "concepcion-premio-miss-realeza" -> "Concepcion"
        - "vincennes-prix-de-paris" -> "Vincennes"
        - "horseshoe-indianapolis-allowance" -> "Horseshoe Indianapolis"
        """
        # Prendre le premier mot (ou les 2 premiers si c'est composé)
        parts = slug.split('-')

        # Cas simple: premier mot
        if len(parts) == 1:
            return parts[0].title()

        # Si le 2e mot ressemble à un complément (pas "prix", "premio", etc.)
        if len(parts) >= 2:
            first = parts[0].title()
            second = parts[1].lower()

            # Mots courants de titre de course à ignorer
            race_keywords = [
                'prix', 'premio', 'allowance', 'claiming', 'maiden',
                'handicap', 'stakes', 'conditions', 'listed', 'group'
            ]

            # Si le 2e mot n'est pas un keyword, c'est probablement
            # un hippodrome composé (ex: "horseshoe-indianapolis")
            if second not in race_keywords:
                return f"{first} {second.title()}"

            return first

        return parts[0].title()

    def _extract_time_near_link(self, link_element) -> str | None:
        """
        Cherche l'heure autour de l'élément <a>

        Sur ZEturf, l'heure est souvent avant le lien:
        "22h30 [R7C4 CONCEPCION]"

        Formats acceptés: 14h30, 14:30, 2h30pm
        """
        # Chercher dans le texte parent
        parent = link_element.find_parent()
        if not parent:
            return None

        # Obtenir le texte complet du parent
        parent_text = parent.get_text()

        # Patterns d'heure
        patterns = [
            r'(\d{1,2})h(\d{2})',           # 14h30
            r'(\d{1,2}):(\d{2})',            # 14:30
            r'(\d{1,2})[h:](\d{2})\s*(?:pm|am)?'  # 2:30pm
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, parent_text, re.IGNORECASE)
            for match in matches:
                hour, minute = match.groups()
                hour = int(hour)
                minute = int(minute)

                # Validation basique
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    # Ajuster si format 12h (pm/am)
                    if 'pm' in parent_text.lower() and hour < 12:
                        hour += 12

                    return f"{hour:02d}:{minute:02d}"

        return None

    def _deduplicate_and_sort(self, plan: list[dict]) -> list[dict]:
        """Déduplique par (date, R, C) et tri par heure"""
        seen = set()
        unique = []

        for race in plan:
            key = (race["date"], race["r_label"], race["c_label"])
            if key not in seen:
                seen.add(key)
                unique.append(race)

        # Tri par heure (celles sans heure en fin)
        def sort_key(r):
            if r["time_local"]:
                try:
                    h, m = r["time_local"].split(':')
                    return (0, int(h), int(m))
                except:
                    pass
            return (1, 99, 99)  # Sans heure -> fin

        unique.sort(key=sort_key)
        return unique


# ============================================================================
# FALLBACK GENY.COM (si besoin)
# ============================================================================

class GenyFallbackParser:
    """
    Parser Geny.com en fallback si ZEturf insuffisant
    NOTE: Structure HTML non vérifiée, à adapter si utilisé
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config.USER_AGENT,
            'Accept': 'text/html',
            'Accept-Language': 'fr-FR,fr;q=0.9',
        })

    def parse_program(self, date_str: str) -> list[dict]:
        """
        Parse Geny.com pour compléter les informations
        URL: https://www.geny.com/courses-pmu/YYYY-MM-DD

        ATTENTION: Structure HTML à vérifier et adapter
        """
        url = f"https://www.geny.com/courses-pmu/{date_str}"

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'lxml')
            races = []

            # TODO: À adapter selon structure HTML réelle Geny
            # Exemple hypothétique:
            race_blocks = soup.find_all('div', class_='race-card')

            for block in race_blocks:
                # Extraire R/C
                rc_text = block.find(class_='race-number')
                if not rc_text:
                    continue

                rc_match = re.search(r'R(\d+)C(\d+)', rc_text.get_text())
                if not rc_match:
                    continue

                r_num, c_num = rc_match.groups()

                # Extraire heure
                time_elem = block.find(class_='race-time')
                time_text = time_elem.get_text() if time_elem else ""
                time_match = re.search(r'(\d{1,2})[h:](\d{2})', time_text)

                time_local = None
                if time_match:
                    h, m = time_match.groups()
                    time_local = f"{int(h):02d}:{int(m):02d}"

                # Extraire hippodrome
                meeting_elem = block.find(class_='hippodrome-name')
                meeting = meeting_elem.get_text().strip() if meeting_elem else "UNKNOWN"

                races.append({
                    "date": date_str,
                    "r_label": f"R{r_num}",
                    "c_label": f"C{c_num}",
                    "meeting": meeting.upper(),
                    "time_local": time_local,
                    "course_url": f"https://www.zeturf.fr/fr/course/{date_str}/R{r_num}C{c_num}",
                    "reunion_url": f"https://www.zeturf.fr/fr/reunion/{date_str}/R{r_num}"
                })

            return races

        except Exception as e:
            logger.error(f"Error parsing Geny: {e}", exc_info=True)
            return []


# ============================================================================
# EXEMPLE D'UTILISATION & TESTS
# ============================================================================

if __name__ == "__main__":
    """
    Test direct du parser ZEturf
    Usage: python -m src.plan
    """
    import sys

    print("🐴 Test du parser ZEturf")
    print("=" * 60)

    # Date à tester (aujourd'hui par défaut)
    date_to_test = sys.argv[1] if len(sys.argv) > 1 else "today"

    builder = PlanBuilder()
    plan = builder.build_plan(date_to_test)

    print(f"\n📅 Date: {date_to_test}")
    print(f"📊 Courses trouvées: {len(plan)}")
    print()

    if not plan:
        print("❌ Aucune course trouvée!")
        print("\n💡 Causes possibles:")
        print("  - Date invalide ou pas de courses ce jour")
        print("  - Structure HTML ZEturf a changé")
        print("  - Throttling (429) ou IP bloquée")
        print("\n🔍 Debug:")
        print("  1. Vérifier manuellement: https://www.zeturf.fr/fr/programmes-et-pronostics")
        print("  2. Augmenter RATE_LIMIT_DELAY dans .env")
        print("  3. Tester avec une autre date")
    else:
        print("✅ Parsing réussi!\n")
        print("📋 Échantillon (5 premières courses):")
        print("-" * 60)

        for i, race in enumerate(plan[:5], 1):
            time_str = race["time_local"] or "??:??"
            print(f"{i}. {race['r_label']}{race['c_label']} - "
                  f"{race['meeting']} - {time_str}")
            print(f"   URL: {race['course_url']}")

        if len(plan) > 5:
            print(f"\n... et {len(plan) - 5} autres courses")

    print()
    print("=" * 60)
    print("✅ Test terminé")
