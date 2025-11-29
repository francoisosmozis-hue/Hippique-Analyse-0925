#!/usr/bin/env python3
import os
import sys

# Simuler environnement Cloud Run
os.environ['TZ'] = 'Europe/Paris'
os.environ['PROJECT_ID'] = 'analyse-hippique'
os.environ['REGION'] = 'europe-west1'

sys.path.insert(0, '.')

from src.plan import build_plan


def main():
    print("\nTesting parser for build_plan...")

    try:
        # The new build_plan function returns a list of races for the day.
        races = build_plan("2025-10-17")
        print(f"\n✅ Success: {len(races)} races found")

        if races:
            for i, race in enumerate(races[:3], 1):
                print(f"\n{i}. {race.get('r_label')}{race.get('c_label')} - {race.get('meeting')}")
                print(f"   Heure: {race.get('time_local')}")
                print(f"   URL: {race.get('course_url')}")
        else:
            print("\n⚠️ No races found.")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
