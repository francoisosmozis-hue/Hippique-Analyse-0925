import requests, pandas as pd, time
from datetime import date, timedelta

def get_json(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def iter_dates_today():
    d = date(2025, 10, 15)
    yield d.strftime("%d%m%Y"), d.isoformat()

rows = []
for dstr, d_iso in iter_dates_today():
    # programme du jour (réunions/courses)
    try:
        prog = get_json(f"https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{dstr}")
    except Exception:
        continue
    reunions = (prog.get("programme") or {}).get("reunions") or []
    for r in reunions:
        R = f"R{r.get('numOfficiel')}"
        courses = r.get("courses") or []
        for c in courses:
            C = f"C{c.get('numOrdre')}"
            # participants + cotes
            try:
                part = get_json(f"https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{dstr}/{R}/{C}/participants")
            except Exception:
                continue
            # arrivée + rapports
            try:
                rap = get_json(f"https://online.turfinfo.api.pmu.fr/rest/client/1/programme/{dstr}/{R}/{C}/rapports-definitifs")
            except Exception:
                rap = {}

            
            # map arrivée: numeroPMU -> rang
            ordre = []
            if isinstance(rap, list):
                for pari in rap:
                    if pari.get("typePari") == "TRIO":
                        rapports = pari.get("rapports", [])
                        if rapports:
                            combinaison = rapports[0].get("combinaison", "")
                            ordre = combinaison.split("-")
                        break
            
            rang = {}
            for i, elt in enumerate(ordre, 1):
                num = elt
                if num is not None:
                    try:
                        rang[int(num)] = i
                    except ValueError:
                        continue

            # lecture des cotes par partant (clé varie selon version, on cherche prudemment)
            participants = part.get("participants") or part.get("chevaux") or []
            for p in participants:
                num = p.get("numeroPmu") or p.get("numPmu") or p.get("numero") or p.get("num")
                nom = (p.get("nom") or p.get("nomCheval") or p.get("cheval", {}).get("nom") or "").strip()
                jockey = (p.get("driver") or p.get("jockey") or p.get("nomJockey") or p.get("nomDriver") or "").strip()
                entraineur = (p.get("entraineur") or p.get("trainer") or "").strip()
                
                # CORRECTED LOGIC
                cote = (p.get("dernierRapportDirect") or {}).get("rapport")

                rows.append({
                    "date": d_iso, "reunion": R, "course": C,
                    "num": num, "cheval": nom, "jockey": jockey, "entraineur": entraineur, "cote": cote,
                    "arrivee_rang": rang.get(int(num)) if num is not None else None
                })
    time.sleep(0.6)  # simple throttle pour rester cool

pd.DataFrame(rows).to_csv("fr_2025_sept_partants_cotes_arrivees.csv", index=False)
print("OK -> fr_2025_sept_partants_cotes_arrivees.csv")

