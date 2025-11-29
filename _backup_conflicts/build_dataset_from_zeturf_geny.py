import argparse
import shlex
import subprocess
from pathlib import Path

THIS = Path(__file__).resolve().parent

def run(cmd: str):
    print(f"[RUN] {cmd}")
    subprocess.run(shlex.split(cmd), check=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--course-url", required=True)
    parser.add_argument("--out-csv", required=True)
    args = parser.parse_args()

    # Utiliser un dossier de sortie simple
    out_dir = Path("data_playwright")
    out_dir.mkdir(exist_ok=True)

    # Appeler le scraper Playwright directement
    playwright_script = THIS / "fetch_with_playwright.py"

    # H-30
    run(f'python "{playwright_script}" --course-url "{args.course_url}" --tag H-30 --out-dir "{out_dir}"')

    # H-5
    run(f'python "{playwright_script}" --course-url "{args.course_url}" --tag H-5 --out-dir "{out_dir}"')

    print("\n[INFO] Scénario de scraping terminé.")
    print(f"Les snapshots devraient se trouver dans le dossier: {out_dir}")
    print("L'intégration de ces snapshots dans le CSV final n'est pas encore implémentée dans ce script simplifié.")

if __name__ == "__main__":
    main()
