import argparse
import logging
from pathlib import Path

import pandas as pd

EXPECTED_COLUMNS = [
    "date",
    "reunion",
    "course",
    "result",
    "roi",
]


def verify_structure(df: pd.DataFrame) -> None:
    """Ensure the DataFrame contains the expected columns.

    Raises:
        ValueError: if any required column is missing.
    """
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Excel file missing required columns: {missing}")


def load_excel(path: Path) -> pd.DataFrame:
    """Load an Excel file and validate its structure."""
    df = pd.read_excel(path)
    verify_structure(df)
    return df


def update_excel(excel_path: Path, results_path: Path) -> None:
    """Append results to the Excel file after validating structure."""
    if excel_path.exists():
        df = load_excel(excel_path)
    else:
        df = pd.DataFrame(columns=EXPECTED_COLUMNS)

    new_rows = pd.read_csv(results_path)
    verify_structure(new_rows)

    updated = pd.concat([df, new_rows], ignore_index=True)
    updated.to_excel(excel_path, index=False)



def main() -> None:
    parser = argparse.ArgumentParser(description="Update Excel with race results")
    parser.add_argument("--excel", required=True, help="Path to Excel workbook")
    parser.add_argument("--results", required=True, help="CSV file with new rows")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")

    excel_path = Path(args.excel)
    results_path = Path(args.results)

    try:
        update_excel(excel_path, results_path)
    except ValueError as exc:
        logging.error("Integrity check failed: %s", exc)
        raise SystemExit(1) from exc
    else:
        logging.info("Excel updated successfully with %s", results_path)


if __name__ == "__main__":
    main()
