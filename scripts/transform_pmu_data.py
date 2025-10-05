
import argparse
import json
from pathlib import Path

def transform_pmu_data(input_path: Path, output_dir: Path, output_filename: str):
    """
    Transforms a PMU participants.json file into the format expected by the analysis pipeline.
    """
    
    with open(input_path, 'r', encoding='utf-8') as f:
        pmu_data = json.load(f)

    runners = []
    participants = pmu_data.get("participants", [])
    
    for p in participants:
        odds = 0.0
        if p.get("dernierRapportDirect") and p["dernierRapportDirect"].get("rapport"):
            odds = p["dernierRapportDirect"]["rapport"]

        runners.append({
            "id": p.get("numPmu"),
            "name": p.get("nom"),
            "odds": odds
        })

    output_data = {"runners": runners}

    output_path = output_dir / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"Successfully transformed {input_path} to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transform PMU participants data.")
    parser.add_argument("--input", required=True, help="Path to the input participants.json file.")
    parser.add_argument("--outdir", required=True, help="Output directory for the JSON snapshot.")
    parser.add_argument("--outfile", required=True, help="Output JSON filename (e.g., h30.json).")
    args = parser.parse_args()
    
    transform_pmu_data(Path(args.input), Path(args.outdir), args.outfile)
