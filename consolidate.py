import json, glob, csv, os

os.makedirs("day_runs", exist_ok=True)
paths = sorted(glob.glob("data/R*C*/analysis_H5.json"))
fields = ["course_id","verdict","roi_estime","tickets","notes"]
rows=[]
for p in paths:
    try:
        with open(p, encoding="utf-8") as f:
            d=json.load(f)
        rows.append({
            "course_id": d.get("course_id"),
            "verdict": d.get("verdict"),
            "roi_estime": d.get("roi_estime"),
            "tickets": "|".join(f"{t.get('type','')}:{t.get('mise','')}" for t in d.get("tickets",[])),
            "notes": d.get("notes","")
        })
    except (json.JSONDecodeError, FileNotFoundError):
        # Ignore broken or missing json files
        continue

with open("day_runs/tracking_jour.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)

print(f"Écrit: day_runs/tracking_jour.csv (lignes: {len(rows)})")
if not rows:
    print("Avertissement: aucun analysis_H5.json trouvé.")
