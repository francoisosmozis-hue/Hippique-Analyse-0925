#!/usr/bin/env python3
"""Compatibility wrapper for :mod:`scripts.online_fetch_zeturf`."""

from scripts.online_fetch_zeturf import main



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


if __name__ == "__main__":  # pragma: no cover
    main()
