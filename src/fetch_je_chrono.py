def enrich_from_snapshot(snapshot_path: str, reunion: str = None, course: str = None) -> str:
    import shlex
    import subprocess
    from pathlib import Path
    p = Path(snapshot_path)
    if not p.exists():
        raise FileNotFoundError(f"snapshot introuvable: {snapshot_path}")
    out = p.parent / "chronos.csv"
    cmd = f'python {Path(__file__).name} --h5 "{p}" --out "{out}"'
    proc = subprocess.run(shlex.split(cmd), check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"fetch_je_chrono failed: {proc.stderr}\n{proc.stdout}")
    return str(out)
def enrich_from_snapshot(snapshot_path: str, reunion: str = None, course: str = None) -> str:
    import shlex
    import subprocess
    from pathlib import Path
    p = Path(snapshot_path)
    if not p.exists():
        raise FileNotFoundError(f"snapshot introuvable: {snapshot_path}")
    out = p.parent / "chronos.csv"
    cmd = f'python {Path(__file__).name} --h5 "{p}" --out "{out}"'
    proc = subprocess.run(shlex.split(cmd), check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"fetch_je_chrono failed: {proc.stderr}\n{proc.stdout}")
    return str(out)
