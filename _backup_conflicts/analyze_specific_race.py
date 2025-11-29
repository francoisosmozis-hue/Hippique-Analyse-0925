
import sys
from hippique_orchestrator.runner import run_course
import uuid
import json

def analyze_race():
    course_url = "https://www.zeturf.fr/fr/course/2025-11-28/R3C4-pau-prix-de-mont-de-marsan"
    race_date = "2025-11-28"
    phase = "H-5" # Assuming full analysis
    correlation_id = str(uuid.uuid4())

    print(f"Starting analysis for {course_url} (Phase: {phase})")
    
    try:
        result = run_course(
            course_url=course_url,
            phase=phase,
            date=race_date,
            correlation_id=correlation_id,
        )
        
        print("\n--- Analysis Result ---")
        print(json.dumps(result, indent=2))
        
        if result.get("ok"):
            print("\n--- SUCCESS ---")
            print("Analysis completed successfully.")
            artifacts = result.get("artifacts", [])
            if artifacts:
                print("Generated artifacts:")
                for artifact in artifacts:
                    print(f"- {artifact}")
            else:
                print("No artifacts were generated.")
        else:
            print("\n--- FAILURE ---")
            print(f"Analysis failed. Reason: {result.get('error', 'Unknown')}")

    except Exception as e:
        print(f"\n--- SCRIPT ERROR ---")
        print(f"An error occurred while running the analysis script: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Add src to path to find the modules
    sys.path.insert(0, './src')
    analyze_race()
