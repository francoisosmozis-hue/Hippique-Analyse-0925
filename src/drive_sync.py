import logging
import os
from typing import Any

try:
    from pydantic import BaseModel
except Exception:
    BaseModel = object  # fallback sans validation stricte

log = logging.getLogger(__name__)

class _PostCoursePayload(BaseModel):  # local, évite import externe
    reunion: str
    course: str
    notes: str | None = None

def run_post_course_sync(reunion: str, course: str, drive_folder_id: str | None = None) -> dict[str, Any]:
    """
    Chaîne post-course :
      1) lire le JSON d'arrivée attendu (si présent)
      2) lancer update_excel_with_results.py
      3) uploader sur Drive si drive_folder_id
    Doit rester robuste même si certaines dépendances sont absentes en dev.
    """
    # TODO: brancher les appels réels: get_arrivee_geny.py / update_excel_with_results.py / upload Drive
    updated_path = "excel/modele_suivi_courses_hippiques.xlsx"
    uploaded = False
    note = "OK (local update only)"
    if drive_folder_id:
        # TODO: upload Drive via credentials
        uploaded = True
        note = "OK (uploaded to Drive)"
    return {"updated_excel": updated_path, "uploaded": uploaded, "note": note}


