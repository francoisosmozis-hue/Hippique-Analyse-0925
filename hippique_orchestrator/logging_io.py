import csv
import json
from collections.abc import Iterable, Mapping
from pathlib import Path

# CSV header for the tracking file.
CSV_HEADER = [
    "reunion",
    "course",
    "hippodrome",
    "date",
    "discipline",
    "partants",
    "nb_tickets",
    "total_stake",
    "total_optimized_stake",
    "ev_sp",
    "ev_global",
    "roi_sp",
    "roi_global",
    "risk_of_ruin",
    "clv_moyen",
    "model",
]



from hippique_orchestrator.gcs_client import get_gcs_manager


def append_csv_line(path: str, data: Mapping[str, object], header: Iterable[str] = CSV_HEADER) -> None:
    """Append a line to a CSV file, with GCS support."""

    gcs_manager = get_gcs_manager()
    if gcs_manager:
        gcs_path = gcs_manager.get_gcs_path(path)

        lines = []
        is_new = not gcs_manager.fs.exists(gcs_path)

        if not is_new:
            with gcs_manager.fs.open(gcs_path, "r", encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh, delimiter=";")
                lines = list(reader)

        # Ensure header is present for new or empty files
        if is_new or not lines:
            lines.insert(0, list(header))

        # Add new data
        lines.append([str(data.get(col, "")) for col in header])

        # Write everything back
        with gcs_manager.fs.open(gcs_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerows(lines)
    else:
        # Original local append logic
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not file_path.exists()
        with file_path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            if is_new:
                writer.writerow(header)
            writer.writerow([str(data.get(col, "")) for col in header])


def append_json(path: str, data: object) -> None:
    """Write JSON data to GCS or local disk."""
    gcs_manager = get_gcs_manager()
    if gcs_manager:
        gcs_path = gcs_manager.get_gcs_path(path)
        with gcs_manager.fs.open(gcs_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
