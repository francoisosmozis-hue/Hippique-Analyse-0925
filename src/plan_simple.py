#!/usr/bin/env python3
"""Plan simplifié pour tester"""

import asyncio
import re

import aiohttp
from bs4 import BeautifulSoup

from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)

async def build_plan_async(date_str: str) -> list[dict]:
    """Construit le plan du jour depuis ZEturf programmes-et-pronostics."""

    url = "https://www.zeturf.fr/fr/programmes-et-pronostics"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html',
    }

    logger.info(f"Building plan for {date_str}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    logger.error(f"HTTP {resp.status} from ZEturf")
                    return []

                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')

                # Pattern pour courses de la date
                pattern = re.compile(rf'/fr/course/{date_str}/R(\d+)C(\d+)')

                races = []
                seen = set()

                for link in soup.find_all('a', href=True):
                    match = pattern.search(link['href'])
                    if match:
                        r, c = int(match.group(1)), int(match.group(2))
                        if (r, c) not in seen:
                            seen.add((r, c))
                            href = link['href']
                            if not href.startswith('http'):
                                href = f"https://www.zeturf.fr{href}"

                            races.append({
                                'date': date_str,
                                'r_label': str(r),
                                'c_label': str(c),
                                'meeting': link.get_text(strip=True)[:50] or f"R{r}",
                                'time_local': '14:00',  # Placeholder
                                'course_url': href,
                                'reunion_url': f"https://www.zeturf.fr/fr/reunion/{date_str}/R{r}"
                            })

                logger.info(f"Found {len(races)} races for {date_str}")
                return sorted(races, key=lambda x: (int(x['r_label']), int(x['c_label'])))

    except Exception as e:
        logger.error(f"Error building plan: {e}")
        return []

# Pour compatibilité
def build_plan(date_str: str) -> list[dict]:
    """Version synchrone."""
    return asyncio.run(build_plan_async(date_str))
