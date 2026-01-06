"""
Client PMU API - Source JSON recommandée
API: https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/

Avantages:
- JSON structuré (pas de HTML à parser)
- Heures précises au format HH:MM:SS
- Données riches (discipline, distance, montant, partants)
- Cotes live disponibles (via /participants)
- Résultats finaux (via /rapports-definitifs)
- Pas de throttling observé
"""

import time
from datetime import datetime

import requests

from .config import config
from .logging_utils import logger


class PMUClient:
    """
    Client pour API PMU (non officielle mais publique)

    Endpoints disponibles:
    - /programme/DDMMYYYY                      → Programme complet
    - /programme/DDMMYYYY/R1                   → Réunion spécifique
    - /programme/DDMMYYYY/R1/C1                → Course spécifique
    - /programme/DDMMYYYY/R1/C1/participants   → Chevaux + cotes live
    - /programme/DDMMYYYY/R1/C1/rapports-definitifs → Résultats
    """

    BASE_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme"

    # Alternative online (si offline échoue)
    ONLINE_BASE_URL = "https://online.turfinfo.api.pmu.fr/rest/client/61/programme"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                'User-Agent': config.USER_AGENT,
                'Accept': 'application/json',
                'Accept-Language': 'fr-FR,fr;q=0.9',
            }
        )

    def get_program(self, date_str: str, use_online: bool = False) -> dict:
        """
        Récupère le programme complet du jour

        Args:
            date_str: "YYYY-MM-DD" (sera converti en DDMMYYYY)
            use_online: Si True, utilise l'API online (plus de données)

        Returns:
            {
                "programme": {
                    "date": "2025-10-16T00:00:00+02:00",
                    "reunions": [...]
                }
            }
        """
        # Convertir YYYY-MM-DD -> DDMMYYYY
        date_pmu = self._convert_date_format(date_str)

        base_url = self.ONLINE_BASE_URL if use_online else self.BASE_URL
        url = f"{base_url}/{date_pmu}"

        logger.info(f"Fetching PMU program: {date_pmu} (online={use_online})")

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()

            data = resp.json()
            logger.info(
                f"PMU program fetched: {len(data.get('programme', {}).get('reunions', []))} réunions"
            )

            return data

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"Programme not found for {date_pmu}")
                return {"programme": {"reunions": []}}
            raise

    def get_reunion(self, date_str: str, reunion_num: int) -> dict:
        """
        Récupère une réunion spécifique

        Args:
            date_str: "YYYY-MM-DD"
            reunion_num: Numéro de réunion (1, 2, 3...)

        Returns:
            Détails de la réunion
        """
        date_pmu = self._convert_date_format(date_str)
        url = f"{self.BASE_URL}/{date_pmu}/R{reunion_num}"

        logger.info(f"Fetching reunion R{reunion_num} for {date_pmu}")

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching reunion R{reunion_num}: {e}")
            return {}

    def get_course(self, date_str: str, reunion_num: int, course_num: int) -> dict:
        """
        Récupère une course spécifique

        Args:
            date_str: "YYYY-MM-DD"
            reunion_num: Numéro de réunion
            course_num: Numéro de course

        Returns:
            Détails de la course
        """
        date_pmu = self._convert_date_format(date_str)
        url = f"{self.BASE_URL}/{date_pmu}/R{reunion_num}/C{course_num}"

        logger.info(f"Fetching course R{reunion_num}C{course_num} for {date_pmu}")

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching course R{reunion_num}C{course_num}: {e}")
            return {}

    def get_participants(self, date_str: str, reunion_num: int, course_num: int) -> list[dict]:
        """
        Récupère les partants avec cotes live

        Args:
            date_str: "YYYY-MM-DD"
            reunion_num: Numéro de réunion
            course_num: Numéro de course

        Returns:
            Liste de chevaux avec:
            - numPmu: Numéro
            - nom: Nom du cheval
            - driver/jockey: Cavalier
            - entraineur: Entraîneur
            - dernierRapportDirect.rapport: Cote live win
            - dernierRapportReference.rapport: Cote référence
        """
        date_pmu = self._convert_date_format(date_str)
        url = f"{self.BASE_URL}/{date_pmu}/R{reunion_num}/C{course_num}/participants"

        logger.info(f"Fetching participants for R{reunion_num}C{course_num}")

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()

            data = resp.json()
            participants = data.get("participants", [])

            logger.info(f"Found {len(participants)} participants")
            return participants

        except Exception as e:
            logger.error(f"Error fetching participants: {e}")
            return []

    def get_results(self, date_str: str, reunion_num: int, course_num: int) -> dict:
        """
        Récupère les résultats finaux

        Args:
            date_str: "YYYY-MM-DD"
            reunion_num: Numéro de réunion
            course_num: Numéro de course

        Returns:
            Rapports définitifs (arrivée, rapports, etc.)
        """
        date_pmu = self._convert_date_format(date_str)
        url = f"{self.BASE_URL}/{date_pmu}/R{reunion_num}/C{course_num}/rapports-definitifs"

        logger.info(f"Fetching results for R{reunion_num}C{course_num}")

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching results: {e}")
            return {}

    def to_plan(self, pmu_data: dict, date_str: str = None) -> list[dict]:
        """
        Convertit JSON PMU en format plan standard

        Args:
            pmu_data: Résultat de get_program()
            date_str: "YYYY-MM-DD" (optionnel, extrait du JSON si absent)

        Returns:
            Liste de courses au format:
            {
                "date": "YYYY-MM-DD",
                "r_label": "R1",
                "c_label": "C3",
                "meeting": "VINCENNES",
                "time_local": "14:15",
                "course_url": "https://www.zeturf.fr/fr/course/...",
                "reunion_url": "https://www.zeturf.fr/fr/reunion/...",
                # Bonus données PMU
                "discipline": "TROT_ATTELE",
                "distance": 2100,
                "montant": 50000,
                "partants": 16
            }
        """
        plan = []

        programme = pmu_data.get("programme", {})

        # Extraire date depuis JSON si non fournie
        if not date_str:
            date_iso = programme.get("date", "")
            date_str = date_iso[:10] if date_iso else None

        reunions = programme.get("reunions", [])

        for reunion in reunions:
            r_num = reunion.get("numOfficiel")
            if not r_num:
                continue

            # Hippodrome
            hippodrome_data = reunion.get("hippodrome", {})
            hippodrome = hippodrome_data.get("libelleCourt", "UNKNOWN")

            # Courses de la réunion
            courses = reunion.get("courses", [])

            for course in courses:
                c_num = course.get("numOrdre")
                if not c_num:
                    continue

                # Extraire heure (format "14:15:00" -> "14:15")
                heure_depart = course.get("heureDepart", "")
                time_local = heure_depart[:5] if heure_depart else None

                # Construire URLs ZEturf
                course_url = (
                    f"https://www.zeturf.fr/fr/course/{date_str}/R{r_num}C{c_num}"
                    if date_str
                    else None
                )
                reunion_url = (
                    f"https://www.zeturf.fr/fr/reunion/{date_str}/R{r_num}" if date_str else None
                )

                race = {
                    "date": date_str,
                    "r_label": f"R{r_num}",
                    "c_label": f"C{c_num}",
                    "meeting": hippodrome,
                    "time_local": time_local,
                    "course_url": course_url,
                    "reunion_url": reunion_url,
                    # Données enrichies PMU
                    "libelle": course.get("libelle", ""),
                    "discipline": course.get("discipline", ""),
                    "distance": course.get("distance"),
                    "montant": course.get("montantPrix"),
                    "partants": course.get("nombreDeclaresPartants"),
                    "specialite": course.get("specialite"),
                    "corde": course.get("corde"),
                }

                plan.append(race)

        logger.info(f"Converted PMU data to plan: {len(plan)} races")
        return plan

    def _convert_date_format(self, date_str: str) -> str:
        """
        Convertit YYYY-MM-DD en DDMMYYYY (format PMU)

        Args:
            date_str: "2025-10-16"
        Returns:
            "16102025"
        """
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d%m%Y")


# ============================================================================
# Exemple d'utilisation
# ============================================================================

if __name__ == "__main__":
    """
    Test du client PMU API
    Usage: python -m src.pmu_client
    """
    import sys

    print("🐴 Test du client PMU API")
    print("=" * 60)

    # Date à tester
    date_to_test = sys.argv[1] if len(sys.argv) > 1 else "2025-10-16"

    client = PMUClient()

    # 1. Programme complet
    print(f"\n📅 Programme du {date_to_test}")
    print("-" * 60)

    try:
        program = client.get_program(date_to_test)
        plan = client.to_plan(program, date_to_test)

        print(f"✅ {len(plan)} courses trouvées\n")

        # Afficher échantillon
        for i, race in enumerate(plan[:5], 1):
            print(
                f"{i}. {race['r_label']}{race['c_label']} - "
                f"{race['meeting']} - {race['time_local']}"
            )
            print(f"   {race['discipline']} - {race['distance']}m - {race['partants']} partants")
            print(f"   Prize: {race['montant']}€")
            print()

        if len(plan) > 5:
            print(f"... et {len(plan) - 5} autres courses")

        # 2. Test participants (première course)
        if plan:
            first_race = plan[0]
            r_num = int(first_race['r_label'][1:])
            c_num = int(first_race['c_label'][1:])

            print(f"\n🐎 Participants {first_race['r_label']}{first_race['c_label']}")
            print("-" * 60)

            participants = client.get_participants(date_to_test, r_num, c_num)

            for p in participants[:3]:
                num = p.get("numPmu")
                nom = p.get("nom")
                jockey = p.get("driver", {}).get("nom", "N/A")

                # Cote
                rapport_direct = p.get("dernierRapportDirect", {})
                cote = rapport_direct.get("rapport", "N/A")

                print(f"  {num}. {nom} - Jockey: {jockey} - Cote: {cote}")

            if len(participants) > 3:
                print(f"  ... et {len(participants) - 3} autres chevaux")

    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback

        traceback.print_exc()

    print()
    print("=" * 60)
    print("✅ Test terminé")
