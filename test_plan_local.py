import sys
from src.plan import build_plan
import json

print("✅ Import plan OK")

try:
    # Using the date from the user's test script
    plan = build_plan("2025-10-17")
    print(f"📊 Courses trouvées: {len(plan)}")

    if plan:
        print("\nExemple de course:")
        print(json.dumps(plan[0], indent=2, ensure_ascii=False))
    else:
        print("⚠️  Plan vide - vérifier les sources ZEturf/Geny")

except Exception as e:
    print(f"❌ Erreur: {e}")
    import traceback

    traceback.print_exc()
