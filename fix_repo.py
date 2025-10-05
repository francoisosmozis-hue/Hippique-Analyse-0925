from pathlib import Path
import re, sys, shutil

def backup(p: Path):
    b = p.with_suffix(p.suffix + ".bak")
    if not b.exists():
        shutil.copy2(p, b)

def patch_runner_chain():
    p = Path("runner_chain.py")
    if not p.exists():
        return "runner_chain.py introuvable"
    t = p.read_text(encoding="utf-8")
    backup(p)
    changed = False

    # Remplace la validation basée sur 'partants' par une validation sur 'runners'
    # Cas 1: lignes explicites partants = snapshot.get("partants")
    t2 = re.sub(
        r'partants\s*=\s*snapshot\.get\("partants"\)\s*\n\s*if\s+not\s+isinstance\(partants,\s*list\)\s*or\s*len\(partants\)\s*==\s*0:\s*\n\s*print\(f"\[runner_chain\]\s*ERREUR: snapshot\s*{[^}]+}\s*vide ou sans \'partants\'\."\s*,\s*file=sys\.stderr\)\s*\n\s*sys\.exit\(2\)',
        'runners = snapshot.get("runners") or []\n'
        'if not isinstance(runners, list) or len(runners) == 0:\n'
        '    print(f"[runner_chain] ERREUR: snapshot {phase} vide ou sans \'runners\'.", file=sys.stderr)\n'
        '    sys.exit(2)',
        t, flags=re.M
    )
    if t2 != t:
        t = t2
        changed = True

    # Cas 2: fonction validate_snapshot_or_die entière à réécrire si nécessaire
    if "def validate_snapshot_or_die" in t and "'runners'" not in t:
        t = re.sub(
            r"def validate_snapshot_or_die\(snapshot:.*?\):\s*\"\"\".*?\"\"\".*?sys\.exit\(2\)\s*",
            (
                'def validate_snapshot_or_die(snapshot: dict, phase: str) -> None:\n'
                '    """Validation robuste: on exige la présence d\'une LISTE de runners."""\n'
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
        p.write_text(t, encoding="utf-8")
        return "runner_chain.py : validation basée sur runners ✅"
    return "runner_chain.py : déjà conforme ✅"

def patch_online_fetch():
    p = Path("online_fetch_zeturf.py")
    if not p.exists():
        return "online_fetch_zeturf.py introuvable"
    t = p.read_text(encoding="utf-8")
    backup(p)
    if "def fetch_race_snapshot(" in t:
        return "online_fetch_zeturf.py : fetch_race_snapshot déjà présent ✅"

    # On ajoute une fonction légère qui réutilise les helpers existants du fichier.
    snippet = r'''
# ----------------------------
# API utilitaire attendue par runner_chain
# ----------------------------
def fetch_race_snapshot(reunion: str, course: str, phase: str = "H5") -> dict:
    """
    Construit un snapshot standard à partir d'une URL de réunion fournie via l'env:
      ZETURF_REUNION_URL = https://www.zeturf.fr/fr/reunion/YYYY-MM-DD/Rx-<slug>
    On parse la réunion, on repère la course R?C? demandée, puis on fabrique
    le JSON { "runners":[...], "partants": int, ... } avec to_pipeline_json(...).
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

    raw = parse_course_page(http_get(target))  # doit retourner runners etc.
    return to_pipeline_json(
        reunion, course, meeting, date_str, target, raw,
        "H-5" if phase.upper()=="H5" else ("H-30" if phase.upper()=="H30" else "manual")
    )
'''
    # Injection avant le bloc main si présent, sinon en fin de fichier
    idx = t.rfind('\nif __name__ == "__main__":')
    if idx == -1:
        t = t.rstrip() + "\n\n" + snippet.strip() + "\n"
    else:
        t = t[:idx] + "\n\n" + snippet + "\n" + t[idx:]
    p.write_text(t, encoding="utf-8")
    return "online_fetch_zeturf.py : fetch_race_snapshot ajouté ✅"

def patch_fetch_je(fname: str, which: str):
    p = Path(fname)
    if not p.exists():
        return f"{fname} introuvable"
    t = p.read_text(encoding="utf-8")
    backup(p)
    if "def enrich_from_snapshot(" in t:
        return f"{fname} : enrich_from_snapshot déjà présent ✅"
    if which == "stats":
        snippet = r'''
def enrich_from_snapshot(snapshot_path: str, reunion: str = "", course: str = "") -> str:
    """
    Lit le JSON H-5, produit <stem>_je.csv (cache activé).
    Retourne le chemin du CSV.
    """
    import subprocess, shlex
    from pathlib import Path
    sp = Path(snapshot_path)
    out = sp.with_name(f"{sp.stem}_je.csv")
    cmd = f'python fetch_je_stats.py --h5 "{sp}" --out "{out}" --cache --ttl-seconds 86400'
    subprocess.run(shlex.split(cmd), check=True)
    return str(out)
'''
    else:
        snippet = r'''
def enrich_from_snapshot(snapshot_path: str, reunion: str = "", course: str = "") -> str:
    """
    Lit le JSON H-5, produit chronos.csv.
    Retourne le chemin du CSV.
    """
    import subprocess, shlex
    from pathlib import Path
    sp = Path(snapshot_path)
    out = sp.with_name("chronos.csv")
    cmd = f'python fetch_je_chrono.py --h5 "{sp}" --out "{out}"'
    subprocess.run(shlex.split(cmd), check=True)
    return str(out)
'''
    t = t.rstrip() + "\n\n" + snippet
    p.write_text(t, encoding="utf-8")
    return f"{fname} : enrich_from_snapshot ajouté ✅"

def patch_pipeline_overround():
    p = Path("pipeline_run.py")
    if not p.exists():
        return "pipeline_run.py introuvable"
    t = p.read_text(encoding="utf-8")
    backup(p)
    changed = False

    # Ajoute helper _place_slots si absent (très basique / fallback)
    if "_place_slots(" not in t:
        t += '\n\ndef _place_slots(n:int)->int:\n    return 2 if n<=7 else (3 if n<=20 else 4)\n'
        changed = True

    # Injecte un compute_overround si absent
    if "def compute_overround(" not in t:
        t += (
            '\n\ndef compute_overround(horses:list, n:int)->float|None:\n'
            '    try:\n'
            '        slots=float(_place_slots(n))\n'
            '        s=sum(h.get("p",0.0) for h in horses)\n'
            '        return (s/slots) if slots>0 else None\n'
            '    except Exception:\n'
            '        return None\n'
        )
        changed = True

    # Essaie de remplacer un return {... "overround": None} par appel compute_overround
    t2 = re.sub(
        r'return\s*\{\s*"n_partants":\s*len\(runners\)\s*,\s*"horses":\s*horses\s*,\s*"overround":\s*None\s*\}',
        'ov = compute_overround(horses, len(runners))\n    return {"n_partants": len(runners), "horses": horses, "overround": ov}',
        t
    )
    if t2 != t:
        t = t2
        changed = True

    if changed:
        p.write_text(t, encoding="utf-8")
        return "pipeline_run.py : overround intégré ✅"
    return "pipeline_run.py : déjà OK ou non nécessaire ✅"

def main():
    msgs = []
    msgs.append(patch_runner_chain())
    msgs.append(patch_online_fetch())
    msgs.append(patch_fetch_je("fetch_je_stats.py", "stats"))
    msgs.append(patch_fetch_je("fetch_je_chrono.py", "chrono"))
    msgs.append(patch_pipeline_overround())
    print("\n".join(msgs))

if __name__ == "__main__":
    main()
