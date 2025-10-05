#!/usr/bin/env python3
import os
import pathlib
import time
from typing import Iterable, List
from google import genai

# --- Réglages ---
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")  # "gemini-1.5-pro" pour +qualité
MAX_FILE_CHARS = 40_000
RATE_DELAY = 0.5
INCLUDE_EXT = {".py", ".yml", ".yaml", ".toml", ".json", ".ini", ".cfg", ".sh", ".md"}
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "data",
    "__pycache__",
    "tests/__snapshots__",
    ".github/workflows/cache",
}
EXCLUDE_FILES = {"schedules.csv"}

PROMPT_HEADER = """Tu es un relecteur senior (Python/CI/GCP). Pour chaque fichier :
1) Résume le rôle (1–2 lignes).
2) Liste 5 risques majeurs (bug/perf/sécu/I-O/réseau).
3) Propose un patch minimal (diff unifié) quand pertinent (sans casser les signatures publiques).
4) Propose 1–2 tests pytest ciblés.
5) Si YAML/CI, vérifie la cohérence et suggère une correction concrète.
Contexte: Analyse Hippique GPI v5.1 (budget 5€, EV/ROI, H-30/H-5, calibration payouts, Kelly 60%, abstention si data manquante).
Répond en Markdown concis et actionnable.
"""


def iter_repo_files(root: str) -> Iterable[pathlib.Path]:
    root = pathlib.Path(root)
    for p in root.rglob("*"):
        if p.is_dir():
            # saute les dossiers exclus
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            continue
        if p.name in EXCLUDE_FILES:
            continue
        if p.suffix in INCLUDE_EXT or p.name == "Dockerfile":
            try:
                if p.stat().st_size > 300_000:
                    continue
                txt = p.read_text(errors="ignore")
                if "\x00" in txt:
                    continue
            except Exception:
                continue
            yield p


def chunk_text(s: str, max_chars: int) -> List[str]:
    if len(s) <= max_chars:
        return [s]
    return [s[i : i + max_chars] for i in range(0, len(s), max_chars)]


def review_file(client: genai.Client, path: pathlib.Path) -> str:
    code = path.read_text(errors="ignore")
    chunks = chunk_text(code, MAX_FILE_CHARS)
    out = []
    for idx, ch in enumerate(chunks, 1):
        header = f"\n\n### {path} (chunk {idx}/{len(chunks)})\n"
        prompt = f"{PROMPT_HEADER}\nFichier : `{path}`\n```text\n{ch}\n```"
        resp = client.models.generate_content(model=MODEL, contents=prompt)
        out.append(header + (getattr(resp, "text", None) or ""))
        time.sleep(RATE_DELAY)
    return "".join(out)


def main():
    client = genai.Client()  # GEMINI_API_KEY (Dev API) ou ADC (Vertex)
    files = sorted(iter_repo_files("."))
    report = ["# Rapport Gemini – Revue du dépôt\n", f"> Modèle : {MODEL}\n"]
    for p in files:
        print(f"[Gemini] Reviewing {p} ...")
        try:
            report.append(review_file(client, p))
        except Exception as e:
            report.append(f"\n\n### {p}\n_Erreur lors de l’analyse: {e}_\n")
    # Synthèse
    synth_prompt = (
        "Synthétise en 15 puces max : risques transverses, quick wins (≤2j),"
        " chantiers (≥1 sem.), TODO priorisés format `- [P0] action (fichier)`."
    )
    resp = client.models.generate_content(
        model=MODEL, contents="".join(report) + "\n" + synth_prompt
    )
    report.append("\n\n## Synthèse priorisée\n" + (getattr(resp, "text", None) or ""))
    pathlib.Path("GEMINI_CODE_REVIEW.md").write_text("".join(report), encoding="utf-8")
    print("✅ Rapport écrit : GEMINI_CODE_REVIEW.md")


if __name__ == "__main__":
    main()
