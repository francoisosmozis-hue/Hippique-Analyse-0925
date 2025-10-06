#!/usr/bin/env python3
"""Export p_finale probabilities and race analysis to CSV/Excel format."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    pd = None  # type: ignore


def load_analysis_file(path: Path) -> Dict[str, Any] | None:
    """Load analysis JSON file."""
    if not path.exists():
        return None
    
    with path.open('r', encoding='utf-8') as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return None


def export_p_finale_from_dir(outputs_dir: Path) -> bool:
    """Export p_finale data from a race output directory.

    Looks for p_finale.json or analysis.json and exports to CSV.

    Parameters
    ----------
    outputs_dir : Path
        Directory containing race outputs

    Returns
    -------
    bool
        True if export succeeded
    """
    if not PANDAS_AVAILABLE:
        print("ERROR: pandas required but not installed", file=sys.stderr)
        return False
    
    # Find p_finale or analysis file
    p_finale_path = outputs_dir / 'p_finale.json'
    analysis_path = outputs_dir / 'analysis.json'
    analysis_h5_path = outputs_dir / 'analysis_H5.json'
    
    data = None
    source_file = None
    
    for candidate in [p_finale_path, analysis_h5_path, analysis_path]:
        if candidate.exists():
            data = load_analysis_file(candidate)
            source_file = candidate
            if data:
                break
    
    if not data:
        print(f"No analysis data found in {outputs_dir}", file=sys.stderr)
        return False
    
    # Extract runners/horses data
    runners = []
    
    # Try different data structures
    if 'runners' in data:
        runners = data['runners']
    elif 'horses' in data:
        runners = data['horses']
    elif 'partants' in data:
        runners = data['partants']
    
    if not runners:
        print(f"No runners found in {source_file}", file=sys.stderr)
        return False
    
    # Build DataFrame
    rows: list[dict[str, Any]] = []
    for runner in runners:
        if not isinstance(runner, dict):
            continue
            
        row = {
            'num': runner.get('num') or runner.get('number') or runner.get('id'),
            'nom': runner.get('nom') or runner.get('name'),
            'p_finale': runner.get('p_finale') or runner.get('p') or runner.get('p_true'),
            'odds': runner.get('odds') or runner.get('cote'),
            'j_rate': runner.get('j_rate') or runner.get('jockey_rate'),
            'e_rate': runner.get('e_rate') or runner.get('trainer_rate'),
        }
        rows.append(row)

    if not rows:
        location = source_file or outputs_dir
        print(f"No valid runner data available in {location}", file=sys.stderr)
        return False

    df = pd.DataFrame(rows)

    csv_path = outputs_dir / 'p_finale_export.csv'
    df.to_csv(csv_path, index=False)

    excel_path = outputs_dir / 'p_finale_export.xlsx'
    df.to_excel(excel_path, index=False)

    print(f"Exported p_finale data to {csv_path} and {excel_path}")
    return True
