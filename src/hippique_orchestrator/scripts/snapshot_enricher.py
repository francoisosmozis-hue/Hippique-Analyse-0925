from __future__ import annotations
import os, json, shutil

def enrich_from_snapshot(snapshot_json: str, out_dir: str, phase: str = "H5", **kwargs):
    """
    Stub no-op : garantit la présence d'un fichier 'snapshot_enriched.json' pour la suite du pipeline.
    À remplacer par l'enrichissement réel (fetch_je_stats + fetch_je_chrono + merge).
    """
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "snapshot_enriched.json")
    try:
        if snapshot_json and os.path.exists(snapshot_json):
            shutil.copyfile(snapshot_json, out)
        else:
            # fallback : écrit un JSON minimal
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"phase": phase, "source": snapshot_json, "enriched": False}, f, ensure_ascii=False)
    except Exception:
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"phase": phase, "source": snapshot_json, "enriched": False}, f, ensure_ascii=False)
    return {"snapshot_enriched": out, "enriched": False}
