"""Fetch time-related features (chronos) for each runner."""

from pathlib import Path
from typing import Union
import pandas as pd


def fetch_je_chrono(source: Union[str, Path]) -> pd.DataFrame:
    """Return chronometric features as a DataFrame.

    Parameters
    ----------
    source: str or Path
        Path to a JSON or CSV file with chrono data.
    """
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() == ".json":
        return pd.read_json(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)

    raise ValueError(f"Unsupported file type: {path.suffix}")

