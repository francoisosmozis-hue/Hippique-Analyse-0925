
import asyncio
import json
import sys

from hippique_orchestrator.plan import build_plan_async


async def find_race():
    # The date is now ignored by plan.py, but we pass it for compatibility
    date_str = "2025-11-10" # The date from the boturfers file
    try:
        # The new plan.py builds the plan from a local html file
        plan = await build_plan_async(date_str)

        target_race = None
        # Looking for R3C4 at Vincennes, as Pau is not in the file
        for race in plan:
            r_label = race.get('r_label', '').upper()
            c_label = race.get('c_label', '').upper()
            meeting_name = race.get('meeting', '').lower()

            if (r_label == 'R3' and
                c_label == 'C4' and
                'vincennes' in meeting_name):
                target_race = race
                break

        if target_race:
            print(json.dumps(target_race, indent=2))
        else:
            # Print known meetings to help debug
            meetings = sorted(list(set([r.get('meeting', 'Unknown') for r in plan])))
            print(f"RACE_NOT_FOUND. Available meetings: {meetings}", file=sys.stderr)

    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Ensure the src directory is in the path to find modules
    sys.path.insert(0, './src')
    asyncio.run(find_race())
