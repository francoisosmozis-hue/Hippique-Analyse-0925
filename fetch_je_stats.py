"""Utilities to load jockey and trainer stats features."""

from pathlib import Path
from typing import Union
import pandas as pd


def fetch_je_stats(source: Union[str, Path]) -> pd.DataFrame:
    """Return jockey/entrant statistics as a DataFrame.

    Parameters
    ----------
    source: str or Path
        Path to a JSON or CSV file containing the features.
    """
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() == ".json":
        return pd.read_json(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)

    raise ValueError(f"Unsupported file type: {path.suffix}")
