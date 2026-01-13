"""
Outil d'aide à la dcouverte d'endpoints d'API ou de donnes embarques.

Ce script fournit des fonctions pour tlcharger une page web et rechercher
des informations potentiellement utiles pour le scraping, telles que :
- Les balises <script> contenant du JSON.
- Les appels rseau (XHR) lists dans les attributs data-*
- Les URL d'API dans le code JavaScript.

Exemple d'utilisation :
python tools/discover_endpoints.py https://www.letrot.com/fiche-personne/1234-nom-jockey
"""

import argparse
import asyncio
import json
import re
from urllib.parse import urljoin  # Moved import to top

import httpx
from bs4 import BeautifulSoup


async def discover_page_data(url: str):
    """
    Tlcharge une URL et analyse son contenu  la recherche de donnes structures.
    """
    print(f"[*] Analyse de l'URL : {url}")

    async with httpx.AsyncClient(headers={"User-Agent": "EndpointDiscoverer/1.0"}, follow_redirects=True) as client:
        try:
            response = await client.get(url, timeout=20.0)
            response.raise_for_status()
            html_content = response.text
            print(f"[+] Page tlcharge avec succs ({len(html_content)} octets).")
        except httpx.RequestError as e:
            print(f"[!] Erreur lors du tlchargement de la page: {e}")
            return

    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Rechercher les balises <script type="application/json"> ou <script type="application/ld+json">
    print("\n[*] Recherche de JSON embarqu dans les balises <script>...")
    json_scripts = soup.find_all('script', type=["application/json", "application/ld+json"])

    if not json_scripts:
        print("[-] Aucune balise <script> avec du JSON trouve.")
    else:
        for i, script in enumerate(json_scripts):
            try:
                json_data = json.loads(script.string)
                print(f"[+] JSON trouv dans le script #{i+1}:")
                # Affiche les 3 premires cls pour donner un aperu
                keys = list(json_data.keys())[:3]
                print(f"    Aperu des cls : {keys}...")
                # print(json.dumps(json_data, indent=2, ensure_ascii=False))
            except (json.JSONDecodeError, TypeError):
                print(f"[!] Le contenu du script #{i+1} n'est pas du JSON valide.")

    # 2. Rechercher des URL d'API dans le code JavaScript inline ou externe
    print("\n[*] Recherche d'URL d'API dans le code JavaScript...")
    js_urls_found = set()

    # Regex pour trouver des chemins d'API courants
    api_pattern = re.compile(r"['\"](/api/v\d+|/graphql|/json-rpc)['\"]")

    for script in soup.find_all('script'):
        # Scripts inline
        if script.string:
            matches = api_pattern.findall(script.string)
            for match in matches:
                js_urls_found.add(match)
        # Scripts externes (src)
        elif script.get('src'):
            src_url = script.get('src')
            if not src_url.startswith(('http:', 'https:')):
                src_url = urljoin(url, src_url)

            # On pourrait aussi télécharger et analyser ces scripts, mais c'est plus complexe
            # print(f"    - Script externe trouvé : {src_url}")

    if not js_urls_found:
        print("[-] Aucune URL d'API évidente trouvée dans le JS.")
    else:
        print("[+] URL d'API potentielles trouvées :")
        for api_url in js_urls_found:
            print(f"    - {api_url}")

    print("\n[*] Analyse terminée.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyse une page web pour aider à la découverte d'endpoints."
    )
    parser.add_argument(
        "url",
        type=str,
        help="L'URL complète de la page à analyser."
    )
    args = parser.parse_args()

    asyncio.run(discover_page_data(args.url))
