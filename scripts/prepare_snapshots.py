import argparse
import csv
import json
from pathlib import Path


def prepare_snapshot(
    csv_path: Path,
    race_reunion: int,
    race_course: int,
    output_dir: Path,
    output_filename: str,
):
    """
    Reads an odds CSV file and creates a JSON snapshot for a specific race.
    """

    runners = []
    race_info = {}

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["R"]) == race_reunion and int(row["C"]) == race_course:
                if not race_info:
                    race_info = {
                        "rc": f"R{row['R']}C{row['C']}",
                        "hippodrome": row["hippodrome"],
                        "date": row["date"],
                        "discipline": row["discipline"],
                    }

                # Use 'rapportDirect' as the odds, fallback to other fields if not available
                odds_val = (
                    row.get("rapportDirect") or row.get("coteDirect") or row.get("cote")
                )

                try:
                    odds = float(odds_val) if odds_val else 0.0
                except (ValueError, TypeError):
                    odds = 0.0

                runners.append({"id": row["num"], "name": row["cheval"], "odds": odds})

    if not runners:
        print(f"No runners found in {csv_path} for race R{race_reunion}C{race_course}")
        return

    output_data = {
        **race_info,
        "runners": runners,
        "id2name": {r["id"]: r["name"] for r in runners},
    }

    output_path = output_dir / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(
        f"Successfully created snapshot {output_path} for race R{race_reunion}C{race_course}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prepare JSON snapshots from an odds CSV file."
    )
    parser.add_argument("--csv", required=True, help="Path to the input odds CSV file.")
    parser.add_argument(
        "--reunion", required=True, type=int, help="Reunion number (e.g., 1)."
    )
    parser.add_argument(
        "--course", required=True, type=int, help="Course number (e.g., 6)."
    )
    parser.add_argument(
        "--outdir", required=True, help="Output directory for the JSON snapshot."
    )
    parser.add_argument(
        "--outfile", required=True, help="Output JSON filename (e.g., h30.json)."
    )
    args = parser.parse_args()

    prepare_snapshot(
        Path(args.csv), args.reunion, args.course, Path(args.outdir), args.outfile
    )
