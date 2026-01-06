"""
Collecteur de statistiques - Jockeys, Entraîneurs, Chevaux

Sources:
1. PMU API /performances-detaillees : Historique cheval (5+ dernières courses)
2. Geny.com : Stats jockey/entraîneur (% victoires, écarts, séquences)

Features ML:
- Performances récentes (musique)
- % réussite jockey/entraîneur
- Écarts depuis dernière victoire
- Association jockey-entraîneur
- Historique sur distance/hippodrome
"""

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from .config import config
from .logging_utils import logger

# ============================================================================
# 1. PMU API - Performances détaillées des chevaux
# ============================================================================


class PMUPerformancesClient:
    """
    Client pour récupérer l'historique des performances des chevaux

    Endpoint: /performances-detaillees/pretty
    """

    BASE_URL = "https://online.turfinfo.api.pmu.fr/rest/client/61/programme"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': config.USER_AGENT, 'Accept': 'application/json'})

    def get_horse_performances(
        self, date_str: str, reunion_num: int, course_num: int
    ) -> list[dict]:
        """
        Récupère les performances détaillées de tous les chevaux d'une course

        Args:
            date_str: "YYYY-MM-DD"
            reunion_num: Numéro réunion
            course_num: Numéro course

        Returns:
            Liste de chevaux avec leurs 5-15 dernières performances:
            [
                {
                    "cheval": "NOM_CHEVAL",
                    "numero": 1,
                    "performances": [
                        {
                            "date": "2025-09-15",
                            "hippodrome": "VINCENNES",
                            "distance": 2100,
                            "discipline": "TROT_ATTELE",
                            "place": 3,
                            "partants": 16,
                            "cote": 5.2
                        },
                        ...
                    ],
                    "stats": {
                        "courses_12_mois": 15,
                        "victoires_12_mois": 3,
                        "places_12_mois": 8,
                        "taux_victoire": 20.0,
                        "taux_place": 53.3
                    }
                },
                ...
            ]
        """
        # Convertir date
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_pmu = dt.strftime("%d%m%Y")

        url = f"{self.BASE_URL}/{date_pmu}/R{reunion_num}/C{course_num}/performances-detaillees/pretty"

        logger.info(f"Fetching performances for R{reunion_num}C{course_num}")

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()

            data = resp.json()

            # Parser les performances
            horses = []
            participants = data.get("participants", [])

            for participant in participants:
                horse_data = self._parse_participant_performances(participant)
                if horse_data:
                    horses.append(horse_data)

            logger.info(f"Retrieved performances for {len(horses)} horses")
            return horses

        except Exception as e:
            logger.error(f"Error fetching performances: {e}")
            return []

    def _parse_participant_performances(self, participant: dict) -> dict | None:
        """Parse les performances d'un participant"""
        try:
            # Infos de base
            cheval_nom = participant.get("nom", "")
            numero = participant.get("numPmu", 0)

            # Performances
            perfs_raw = participant.get("performances", [])
            performances = []

            for perf in perfs_raw[:15]:  # Max 15 dernières
                performances.append(
                    {
                        "date": perf.get("date", "")[:10],
                        "hippodrome": perf.get("hippodrome", {}).get("libelleCourt", ""),
                        "distance": perf.get("distance"),
                        "discipline": perf.get("discipline", ""),
                        "place": perf.get("place"),
                        "partants": perf.get("nombrePartants"),
                        "cote": perf.get("rapport"),
                        "gains": perf.get("allocation"),
                    }
                )

            # Calcul stats 12 mois
            stats = self._compute_stats(performances)

            return {
                "cheval": cheval_nom,
                "numero": numero,
                "performances": performances,
                "stats": stats,
            }

        except Exception as e:
            logger.warning(f"Error parsing participant: {e}")
            return None

    def _compute_stats(self, performances: list[dict]) -> dict:
        """Calcule les statistiques sur 12 mois"""
        if not performances:
            return {
                "courses_12_mois": 0,
                "victoires_12_mois": 0,
                "places_12_mois": 0,
                "taux_victoire": 0.0,
                "taux_place": 0.0,
            }

        # Filtrer 12 derniers mois
        from datetime import datetime, timedelta

        cutoff_date = datetime.now() - timedelta(days=365)

        courses = 0
        victoires = 0
        places = 0  # Places 2-5

        for perf in performances:
            try:
                perf_date = datetime.strptime(perf["date"], "%Y-%m-%d")
                if perf_date >= cutoff_date:
                    courses += 1
                    place = perf.get("place")
                    if place == 1:
                        victoires += 1
                        places += 1  # Victoire compte comme place
                    elif place and 2 <= place <= 5:
                        places += 1
            except:
                continue

        taux_victoire = (victoires / courses * 100) if courses > 0 else 0.0
        taux_place = (places / courses * 100) if courses > 0 else 0.0

        return {
            "courses_12_mois": courses,
            "victoires_12_mois": victoires,
            "places_12_mois": places,
            "taux_victoire": round(taux_victoire, 1),
            "taux_place": round(taux_place, 1),
        }


# ============================================================================
# 2. GENY - Statistiques Jockeys et Entraîneurs
# ============================================================================


class GenyStatsParser:
    """
    Parser pour statistiques jockey/entraîneur sur Geny.com

    Données disponibles:
    - % victoires et places sur 12 mois
    - Séquence des performances (musique)
    - Écart depuis dernière victoire/place
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                'User-Agent': config.USER_AGENT,
                'Accept': 'text/html',
                'Accept-Language': 'fr-FR,fr;q=0.9',
            }
        )

    def get_course_stats(self, date_str: str, reunion_num: int, course_num: int) -> dict:
        """
        Récupère les statistiques jockey/entraîneur pour une course

        Args:
            date_str: "YYYY-MM-DD"
            reunion_num: Numéro réunion
            course_num: Numéro course

        Returns:
            {
                "jockeys": {
                    "NOM_JOCKEY": {
                        "pct_victoires": 15.2,
                        "pct_places": 45.8,
                        "courses_12_mois": 120,
                        "victoires_12_mois": 18,
                        "ecart_victoire": 3,
                        "musique": "1p3p5p2p"
                    },
                    ...
                },
                "entraineurs": {
                    "NOM_ENTRAINEUR": {
                        "pct_victoires": 12.5,
                        "pct_places": 38.2,
                        ...
                    },
                    ...
                }
            }
        """
        # URL page partants Geny
        url = f"https://www.geny.com/partants-pmu/{date_str}-R{reunion_num}-C{course_num}"

        logger.info(f"Fetching Geny stats for R{reunion_num}C{course_num}")

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'lxml')

            # Parser jockeys
            jockeys = self._parse_jockey_stats(soup)

            # Parser entraîneurs
            entraineurs = self._parse_trainer_stats(soup)

            return {"jockeys": jockeys, "entraineurs": entraineurs}

        except Exception as e:
            logger.error(f"Error fetching Geny stats: {e}")
            return {"jockeys": {}, "entraineurs": {}}

    def _parse_jockey_stats(self, soup: BeautifulSoup) -> dict[str, dict]:
        """
        Parse les statistiques des jockeys depuis la page

        Structure Geny (à adapter selon HTML réel):
        - Bloc jockey avec nom
        - % victoires et places
        - Musique des performances
        """
        jockeys = {}

        # Chercher les blocs jockeys
        # NOTE: Sélecteurs CSS à adapter selon structure HTML réelle
        jockey_blocks = soup.find_all('div', class_=re.compile(r'jockey|driver'))

        for block in jockey_blocks:
            try:
                # Nom jockey
                nom_elem = block.find(class_=re.compile(r'nom|name'))
                if not nom_elem:
                    continue
                nom = nom_elem.get_text(strip=True)

                # Statistiques
                stats_text = block.get_text()

                # Parser % victoires (ex: "15%")
                pct_victoires = self._extract_percentage(stats_text, r'(\d+\.?\d*)%.*victoire')
                pct_places = self._extract_percentage(stats_text, r'(\d+\.?\d*)%.*place')

                # Parser musique (ex: "1p3p5p2p")
                musique = self._extract_musique(stats_text)

                # Parser écart (ex: "Écart: 3")
                ecart = self._extract_ecart(stats_text)

                jockeys[nom] = {
                    "pct_victoires": pct_victoires,
                    "pct_places": pct_places,
                    "musique": musique,
                    "ecart_victoire": ecart,
                }

            except Exception as e:
                logger.debug(f"Error parsing jockey block: {e}")
                continue

        return jockeys

    def _parse_trainer_stats(self, soup: BeautifulSoup) -> dict[str, dict]:
        """Parse les statistiques des entraîneurs"""
        entraineurs = {}

        # Structure similaire aux jockeys
        trainer_blocks = soup.find_all('div', class_=re.compile(r'entraineur|trainer'))

        for block in trainer_blocks:
            try:
                nom_elem = block.find(class_=re.compile(r'nom|name'))
                if not nom_elem:
                    continue
                nom = nom_elem.get_text(strip=True)

                stats_text = block.get_text()

                entraineurs[nom] = {
                    "pct_victoires": self._extract_percentage(
                        stats_text, r'(\d+\.?\d*)%.*victoire'
                    ),
                    "pct_places": self._extract_percentage(stats_text, r'(\d+\.?\d*)%.*place'),
                    "musique": self._extract_musique(stats_text),
                    "ecart_victoire": self._extract_ecart(stats_text),
                }

            except Exception as e:
                logger.debug(f"Error parsing trainer block: {e}")
                continue

        return entraineurs

    def _extract_percentage(self, text: str, pattern: str) -> float | None:
        """Extrait un pourcentage depuis le texte"""
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except:
                pass
        return None

    def _extract_musique(self, text: str) -> str | None:
        """
        Extrait la musique (séquence de performances)
        Format: "1p3p5p2p" (1=1er, p=plat, 3=3ème, etc.)
        """
        # Pattern: suite de chiffres/lettres
        match = re.search(r'[0-9DATa-z]{8,20}', text)
        if match:
            musique = match.group()
            # Vérifier que c'est bien une musique (contient des chiffres)
            if any(c.isdigit() for c in musique):
                return musique
        return None

    def _extract_ecart(self, text: str) -> int | None:
        """Extrait l'écart (courses depuis dernière victoire)"""
        match = re.search(r'[ÉEé]cart[:\s]+(\d+)', text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except:
                pass
        return None


# ============================================================================
# 3. Collecteur unifié
# ============================================================================


class StatsCollector:
    """
    Collecteur unifié de statistiques pour ML

    Combine:
    - Performances chevaux (PMU API)
    - Stats jockeys (Geny)
    - Stats entraîneurs (Geny)
    """

    def __init__(self):
        self.pmu_client = PMUPerformancesClient()
        self.geny_parser = GenyStatsParser()

    def collect_all_stats(self, date_str: str, reunion_num: int, course_num: int) -> dict:
        """
        Collecte toutes les statistiques pour une course

        Returns:
            {
                "chevaux": [...],
                "jockeys": {...},
                "entraineurs": {...}
            }
        """
        logger.info(f"Collecting stats for R{reunion_num}C{course_num}")

        # 1. Performances chevaux (PMU)
        chevaux = self.pmu_client.get_horse_performances(date_str, reunion_num, course_num)

        # 2. Stats jockeys/entraîneurs (Geny)
        geny_stats = self.geny_parser.get_course_stats(date_str, reunion_num, course_num)

        return {
            "chevaux": chevaux,
            "jockeys": geny_stats.get("jockeys", {}),
            "entraineurs": geny_stats.get("entraineurs", {}),
        }

    def export_for_ml(self, stats: dict) -> list[dict]:
        """
        Exporte les stats au format ML-ready

        Returns:
            Liste de features par cheval:
            [
                {
                    "cheval": "NOM",
                    "numero": 1,
                    # Features cheval
                    "nb_courses_12m": 15,
                    "nb_victoires_12m": 3,
                    "taux_victoire_cheval": 20.0,
                    # Features jockey
                    "taux_victoire_jockey": 15.2,
                    "ecart_jockey": 3,
                    # Features entraîneur
                    "taux_victoire_entraineur": 12.5,
                    # Dernières perfs
                    "last_5_places": [3, 1, 5, 2, 4],
                    ...
                },
                ...
            ]
        """
        ml_data = []

        for cheval_data in stats.get("chevaux", []):
            features = {
                "cheval": cheval_data["cheval"],
                "numero": cheval_data["numero"],
                # Stats cheval
                "nb_courses_12m": cheval_data["stats"]["courses_12_mois"],
                "nb_victoires_12m": cheval_data["stats"]["victoires_12_mois"],
                "taux_victoire_cheval": cheval_data["stats"]["taux_victoire"],
                "taux_place_cheval": cheval_data["stats"]["taux_place"],
                # Dernières performances
                "last_5_places": [p.get("place") for p in cheval_data["performances"][:5]],
                # TODO: Ajouter jockey/entraîneur via matching
            }

            ml_data.append(features)

        return ml_data


# ============================================================================
# Test & Example
# ============================================================================

if __name__ == "__main__":
    """
    Test du collecteur de stats
    Usage: python -m src.stats_collector
    """
    import sys
    from pprint import pprint

    print("📊 Test Collecteur de Statistiques")
    print("=" * 60)

    # Arguments
    date_str = sys.argv[1] if len(sys.argv) > 1 else "2025-10-16"
    r_num = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    c_num = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    print(f"Course: {date_str} R{r_num}C{c_num}\n")

    collector = StatsCollector()

    # Collecter stats
    stats = collector.collect_all_stats(date_str, r_num, c_num)

    print("📊 Résultats")
    print("-" * 60)
    print(f"Chevaux: {len(stats['chevaux'])}")
    print(f"Jockeys: {len(stats['jockeys'])}")
    print(f"Entraîneurs: {len(stats['entraineurs'])}\n")

    # Afficher échantillon
    if stats['chevaux']:
        print("🐎 Premier cheval:")
        pprint(stats['chevaux'][0], indent=2)

    print("\n" + "=" * 60)
    print("✅ Test terminé")
