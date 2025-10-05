from pathlib import Path
import re, shutil

def backup(p: Path):
    b = p.with_suffix(p.suffix + ".bak")
    if not b.exists():
        try: shutil.copy2(p, b)
        except Exception: pass

def patch_runner_chain_file(path: Path) -> str:
    if not path.exists(): return f"{path}: introuvable"
    t = path.read_text(encoding="utf-8")
    backup(path)
    changed = False

    # 1) Remplacer logique 'partants' -> 'runners' si présente
    t2 = re.sub(
        r'partants\s*=\s*snapshot\.get\("partants"\)\s*\n\s*if\s+not\s+isinstance\(partants,\s*list\)\s*or\s*len\(partants\)\s*==\s*0:\s*\n\s*print\(f"\[runner_chain\]\s*ERREUR: snapshot\s*\{[^}]+}.*?\'partants\'.*?\)\s*\n\s*sys\.exit\(2\)',
        'runners = snapshot.get("runners") or []\n'
        'if not isinstance(runners, list) or len(runners) == 0:\n'
        '    print(f"[runner_chain] ERREUR: snapshot {phase} vide ou sans \'runners\'.", file=sys.stderr)\n'
        '    sys.exit(2)',
        t, flags=re.M|re.S
    )
    if t2 != t:
        t = t2
        changed = True

    # 2) Si la fonction existe mais ne valide pas 'runners', on remplace la définition
    if "def validate_snapshot_or_die" in t and "'runners'" not in t:
        t = re.sub(
            r"def validate_snapshot_or_die\(.*?\):.*?sys\.exit\(2\)\s*",
            (
                'def validate_snapshot_or_die(snapshot: dict, phase: str) -> None:\n'
                '    """Validation robuste: exige une LISTE de runners."""\n'
                '    if not isinstance(snapshot, dict):\n'
                '        print(f"[runner_chain] ERREUR: snapshot {phase} invalide (type).", file=sys.stderr)\n'
                '        sys.exit(2)\n'
                '    runners = snapshot.get("runners") or []\n'
                '    if not isinstance(runners, list) or len(runners) == 0:\n'
                '        print(f"[runner_chain] ERREUR: snapshot {phase} vide ou sans \'runners\'.", file=sys.stderr)\n'
                '        sys.exit(2)\n'
            ),
            t, flags=re.S
        )
        changed = True

    if changed:
        path.write_text(t, encoding="utf-8")
        return f"{path}: validation runners ✅"
    return f"{path}: déjà conforme ✅"

def patch_online_fetch_file(path: Path) -> str:
    if not path.exists(): return f"{path}: introuvable"
    t = path.read_text(encoding="utf-8")
    backup(path)
    if "def fetch_race_snapshot(" in t:
        return f"{path}: fetch_race_snapshot déjà présent ✅"
    snippet = r'''
# ----------------------------
# API utilitaire attendue par runner_chain
# ----------------------------
def fetch_race_snapshot(reunion: str, course: str, phase: str = "H5") -> dict:
    """
    Construit un snapshot standard à partir d'une URL de réunion fournie via l'env:
      ZETURF_REUNION_URL = https://www.zeturf.fr/fr/reunion/YYYY-MM-DD/Rx-<slug>
    On parse la réunion, on repère la course R?C? demandée, puis on fabrique
    le JSON standard avec to_pipeline_json(...).
    """
    import os, re, datetime as dt
    reunion = str(reunion).upper().strip()
    course  = str(course).upper().strip()
    label   = f"{reunion}{course}"
    rurl = os.getenv("ZETURF_REUNION_URL", "").split("#",1)[0]
    if not rurl:
        raise RuntimeError("ZETURF_REUNION_URL non défini. export ZETURF_REUNION_URL='<url réunion>'")

    html = http_get(rurl)
    pairs = parse_meeting_page(html)  # -> List[Tuple[label, url_course]]
    target = None
    for lab, url in pairs:
        if lab.upper() == label:
            target = url.split("#",1)[0]
            break
    if not target:
        raise RuntimeError(f"Course {label} introuvable dans la réunion fournie")

    mdate = re.search(r"/reunion/(\\d{4}-\\d{2}-\\d{2})/", rurl)
    date_str = mdate.group(1) if mdate else dt.date.today().isoformat()
    mmeet = re.search(r"/reunion/\\d{4}-\\d{2}-\\d{2}/(R\\d+)-([a-z0-9\\-]+)", rurl, re.I)
    meeting = (mmeet.group(2).replace("-", " ") if mmeet else "").title()

    raw = parse_course_page(http_get(target))
    return to_pipeline_json(
        reunion, course, meeting, date_str, target, raw,
        "H-5" if phase.upper()=="H5" else ("H-30" if phase.upper()=="H30" else "manual")
    )
'''
    idx = t.rfind('\nif __name__ == "__main__":')
    t = (t[:idx] + "\n\n" + snippet + "\n" + t[idx:]) if idx != -1 else (t.rstrip() + "\n\n" + snippet + "\n")
    path.write_text(t, encoding="utf-8")
    return f"{path}: fetch_race_snapshot ajouté ✅"

def patch_fetch_je_file(path: Path, kind: str) -> str:
    if not path.exists(): return f"{path}: introuvable"
    t = path.read_text(encoding="utf-8")
    backup(path)
    if "def enrich_from_snapshot(" in t:
        return f"{path}: enrich_from_snapshot déjà présent ✅"

    # Déterminer la commande python relative
    rel = path.as_posix()
    if kind == "stats":
        snippet = f'''
def enrich_from_snapshot(snapshot_path: str, reunion: str = "", course: str = "") -> str:
    """
    Lit le JSON H-5, produit <stem>_je.csv (cache activé).
    Retourne le chemin du CSV.
    """
    import subprocess, shlex
    from pathlib import Path
    sp = Path(snapshot_path)
    out = sp.with_name(f"{{sp.stem}}_je.csv")
    cmd = f'python {rel} --h5 "{{sp}}" --out "{{out}}" --cache --ttl-seconds 86400'
    subprocess.run(shlex.split(cmd), check=True)
    return str(out)
'''
    else:
        snippet = f'''
def enrich_from_snapshot(snapshot_path: str, reunion: str = "", course: str = "") -> str:
    """
    Lit le JSON H-5, produit chronos.csv.
    Retourne le chemin du CSV.
    """
    import subprocess, shlex
    from pathlib import Path
    sp = Path(snapshot_path)
    out = sp.with_name("chronos.csv")
    cmd = f'python {rel} --h5 "{{sp}}" --out "{{out}}"'
    subprocess.run(shlex.split(cmd), check=True)
    return str(out)
'''
    t = t.rstrip() + "\n\n" + snippet
    path.write_text(t, encoding="utf-8")
    return f"{path}: enrich_from_snapshot ajouté ✅"

def main():
    msgs = []
    # runner_chain aux deux emplacements
    for f in [Path("runner_chain.py"), Path("scripts/runner_chain.py")]:
        msgs.append(patch_runner_chain_file(f))
    # online_fetch aux deux emplacements
    for f in [Path("online_fetch_zeturf.py"), Path("scripts/online_fetch_zeturf.py")]:
        if f.exists(): msgs.append(patch_online_fetch_file(f))
    # JE/Chronos aux deux emplacements
    msgs.append(patch_fetch_je_file(Path("fetch_je_stats.py"), "stats") if Path("fetch_je_stats.py").exists() else "fetch_je_stats.py: absent à la racine (OK)")
    msgs.append(patch_fetch_je_file(Path("fetch_je_chrono.py"), "chrono") if Path("fetch_je_chrono.py").exists() else "fetch_je_chrono.py: absent à la racine (OK)")
    msgs.append(patch_fetch_je_file(Path("scripts/fetch_je_stats.py"), "stats"))
    msgs.append(patch_fetch_je_file(Path("scripts/fetch_je_chrono.py"), "chrono"))
    print("\n".join(msgs))

if __name__ == "__main__":
    main()
