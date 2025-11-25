#!/usr/bin/env bash
set -euo pipefail
SERVICE_URL="${SERVICE_URL:?Set SERVICE_URL}"
INPUT="${1:-day_runs/races_today.json}"
LOGDIR="${LOGDIR:-logs}"
TZ="${TZ:-Europe/Paris}"
mkdir -p "$LOGDIR" day_runs
export TZ

emit_lines() {
  python - <<'PY'
import json,sys
with open(sys.argv[1],encoding='utf-8') as f:
    data=json.load(f)
for it in data:
    print("\t".join([
        it.get("label",""),
        it.get("reunion",""),
        it.get("course",""),
        it.get("heure_depart",""),
        it.get("course_url","")
    ]))
PY
}
secs_until() {
  local hhmm="$1"
  local today="$(date +%Y-%m-%d)"
  local target_ts="$(date -d "$today $hhmm:00" +%s)"
  local now_ts="$(date +%s)"
  echo $(( target_ts - now_ts ))
}
run_h30() {
  local label="$1" rcurl="$2" reunion="$3" course="$4"
  echo ">>> [H-30] $label"
  if [[ -n "$rcurl" ]]; then
    curl -sS -X POST "$SERVICE_URL/analyse" -H 'content-type: application/json' \
      -d "{\"phase\":\"H30\",\"course_url\":\"$rcurl\",\"budget\":5}" | tee "$LOGDIR/${reunion}${course}_H30.log" >/dev/null
  else
    curl -sS -X POST "$SERVICE_URL/analyse" -H 'content-type: application/json' \
      -d "{\"phase\":\"H30\",\"reunion\":\"$reunion\",\"course\":\"$course\",\"budget\":5}" | tee "$LOGDIR/${reunion}${course}_H30.log" >/dev/null
  fi
}
run_h5() {
  local label="$1" reunion="$2" course="$3"
  echo ">>> [H-5]  $label"
  curl -sS -X POST "$SERVICE_URL/pipeline/run" -H 'content-type: application/json' \
    -d "{\"reunion\":\"$reunion\",\"course\":\"$course\",\"phase\":\"H5\",\"budget\":5}" | tee "$LOGDIR/${reunion}${course}_H5.log" >/dev/null
}
schedule_one() {
  local label="$1" reunion="$2" course="$3" hhmm="$4" rcurl="$5"
  local dt_h30="$(secs_until "$hhmm")"; local wait_h30=$(( dt_h30 - 1800 )); [[ $wait_h30 -lt 0 ]] && wait_h30=0
  local dt_h5="$(secs_until "$hhmm")";  local wait_h5=$(( dt_h5 - 300 ));  [[ $wait_h5 -lt 0 ]] && wait_h5=0
  ( [[ $wait_h30 -gt 0 ]] && sleep "$wait_h30"; run_h30 "$label" "$rcurl" "$reunion" "$course" ) &
  ( [[ $wait_h5 -gt 0 ]] && sleep "$wait_h5"; run_h5  "$label"        "$reunion" "$course" ) &
}
echo ">> Chargement (Python) : $INPUT"
idx=0
while IFS=$'\t' read -r label reunion course heure url; do
  [[ -z "$label" || -z "$reunion" || -z "$course" || -z "$heure" ]] && continue
  if [[ $(secs_until "$heure") -le 0 ]]; then
    echo ">> $label ($heure) déjà entamé → H-30 & H-5 immédiats"
    run_h30 "$label" "$url" "$reunion" "$course"
    run_h5  "$label"        "$reunion" "$course"
  else
    schedule_one "$label" "$reunion" "$course" "$heure" "$url"
  fi
  idx=$((idx+1))
done < <(emit_lines "$INPUT")
echo ">> Courses programmées: $idx. Attente des jobs…"
wait || true
# Tracking CSV
python - <<'PY'
import json, glob, csv, os
os.makedirs("day_runs", exist_ok=True)
paths = sorted(glob.glob("data/R*C*/analysis_H5.json"))
fields = ["course_id","verdict","roi_estime","tickets","notes"]
rows=[]
for p in paths:
    with open(p, encoding="utf-8") as f:
        d=json.load(f)
    rows.append({
        "course_id": d.get("course_id"),
        "verdict": d.get("verdict"),
        "roi_estime": d.get("roi_estime"),
        "tickets": "|".join(f"{t.get('type','')}:{t.get('mise','')}" for t in d.get("tickets",[])),
        "notes": d.get("notes","")
    })
with open("day_runs/tracking_jour.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
print(f"Écrit: day_runs/tracking_jour.csv (lignes: {len(rows)})")
if not rows:
    print("Avertissement: aucun analysis_H5.json trouvé. As-tu laissé le script tourner jusqu'à H-5 ?")
PY
echo ">> Terminé."
