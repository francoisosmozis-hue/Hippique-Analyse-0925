# --- helper importable pour runner_chain / analyse_courses -------------------
def enrich_from_snapshot(snapshot_path: str, reunion: str = None, course: str = None) -> str:
    """
    Compatibilité: lit le JSON snapshot, et exécute le main flow pour produire *_je.csv
    Retourne le chemin du CSV généré (string) ou lève exception.
    """
    from pathlib import Path
    import json, subprocess, shlex
    p = Path(snapshot_path)
    if not p.exists():
        raise FileNotFoundError(f"snapshot introuvable: {snapshot_path}")
    # Par défaut, génère <stem>_je.csv à côté du snapshot
    out = p.parent / f"{p.stem}_je.csv"
    # Appel interne au main via subprocess pour réutiliser le code existant proprement
    cmd = f'python {Path(__file__).name} --h5 "{p}" --out "{out}" --cache --ttl-seconds 86400'
    proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"fetch_je_stats failed: {proc.stderr}\n{proc.stdout}")
    return str(out)
# --- helper importable pour runner_chain / analyse_courses -------------------
def enrich_from_snapshot(snapshot_path: str, reunion: str = None, course: str = None) -> str:
    """
    Compatibilité: lit le JSON snapshot, et exécute le main flow pour produire *_je.csv
    Retourne le chemin du CSV généré (string) ou lève exception.
    """
    from pathlib import Path
    import json, subprocess, shlex
    p = Path(snapshot_path)
    if not p.exists():
        raise FileNotFoundError(f"snapshot introuvable: {snapshot_path}")
    # Par défaut, génère <stem>_je.csv à côté du snapshot
    out = p.parent / f"{p.stem}_je.csv"
    # Appel interne au main via subprocess pour réutiliser le code existant proprement
    cmd = f'python {Path(__file__).name} --h5 "{p}" --out "{out}" --cache --ttl-seconds 86400'
    proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"fetch_je_stats failed: {proc.stderr}\n{proc.stdout}")
    return str(out)
