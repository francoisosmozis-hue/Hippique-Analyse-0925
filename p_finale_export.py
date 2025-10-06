from __future__ import annotations
from pathlib import Path
import json

__all__ = ["export"]

def export(p_finale: dict, out_path: str | Path = "p_finale_export.json") -> Path:
    """
    Écrit `p_finale` en JSON à `out_path` et retourne le Path.
    UTF-8, indenté, clés ordonnées (pour des tests stables).
    """
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(p_finale, f, ensure_ascii=False, indent=2, sort_keys=True)
    return p
