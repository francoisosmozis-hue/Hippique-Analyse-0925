#!/usr/bin/env python3
"""
scheduler_plan.py — planifie les jobs journaliers (H30, H5, RESULT)
"""
import datetime as dt
import os

import requests

SERVICE_URL = os.getenv("SERVICE_URL") or "https://hippique-orchestrator-1084663881709.europe-west4.run.app"

def plan_day():
    races_today = [
        {"reunion": "R1", "course": "C1", "hour": "13:40"},
        {"reunion": "R1", "course": "C2", "hour": "14:10"},
        # … à automatiser avec online_fetch_zeturf.py si besoin
    ]
    now = dt.datetime.now()
    for r in races_today:
        for phase, offset in [("H30", -30), ("H5", -5), ("RESULT", 10)]:
            target = (dt.datetime.strptime(r["hour"], "%H:%M") +
                      dt.timedelta(minutes=offset))
            delay = max(0, (target - now).total_seconds())
            print(f"Programmation {r['reunion']}{r['course']} {phase} dans {delay/60:.1f} min")
            requests.post(f"{SERVICE_URL}/pipeline/run",
                          json={"reunion": r["reunion"], "course": r["course"],
                                "phase": phase, "budget": 5})

if __name__ == "__main__":
    plan_day()
