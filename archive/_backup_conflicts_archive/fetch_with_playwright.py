# pip install playwright
# python -m playwright install chromium
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def get_course_json(page, url):
    page.goto(url, wait_until="domcontentloaded")
    # Attendre que les XHR peuplent la page (adapter le sélecteur si nécessaire)
    page.wait_for_timeout(3000)  # Augmenté pour plus de robustesse

    content = page.content()
    # Plan A: détecter un <script type="application/json"> ou un data-state
    data = None
    script_tag = page.query_selector('script[type="application/json"]')
    if script_tag:
        data = json.loads(script_tag.inner_text())

    if not data:
        start = content.find('data-state="')
        if start != -1:
            start += len('data-state="')
            end = content.find('"', start)
            data = json.loads(bytes(content[start:end], "utf-8").decode("unicode_escape"))

    # Plan B: intercepter window.__INITIAL_STATE__
    if not data:
        data = page.evaluate("() => window.__INITIAL_STATE__ || null")

    return data


def snapshot_odds(course_url, tag, out_dir):
    print(f"[Playwright] Lancement pour {course_url} (tag: {tag})")
    out_path = Path(out_dir) / f"snapshot_{tag}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = ctx.new_page()

        try:
            data = get_course_json(page, course_url)
            if data:
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"[Playwright] Snapshot sauvegardé dans {out_path}")
            else:
                print("[Playwright] ERREUR: Aucune donnée JSON n'a pu être extraite de la page.")
        except Exception as e:
            print(f"[Playwright] Une erreur est survenue: {e}")
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description="Crée un snapshot de cotes avec Playwright.")
    parser.add_argument("--course-url", required=True, help="URL de la course ZEturf")
    parser.add_argument("--tag", required=True, help="Tag pour le snapshot (ex: H-30, H-5)")
    parser.add_argument("--out-dir", required=True, help="Dossier de sortie pour le JSON")
    args = parser.parse_args()

    snapshot_odds(args.course_url, args.tag, args.out_dir)


if __name__ == "__main__":
    main()
