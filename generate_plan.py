import json
from pathlib import Path
from src.plan import build_plan

# Define the output path
output_dir = Path("data/planning")
output_dir.mkdir(parents=True, exist_ok=True)
output_file = output_dir / "planning-2025-10-17.json"

print(f"Generating plan for 2025-10-17...")

try:
    # Build the plan
    plan_data = build_plan("2025-10-17")

    # Save the plan to a JSON file
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(plan_data, f, indent=2, ensure_ascii=False)

    print(f"✅ Plan successfully generated and saved to {output_file}")
    print(f"Total courses found: {len(plan_data)}")

except Exception as e:
    print(f"❌ Error generating plan: {e}")
    import traceback
    traceback.print_exc()
