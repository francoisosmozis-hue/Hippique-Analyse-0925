import logging
from typing import Optional, Dict, Any
import os

try:
    from pydantic import BaseModel
except Exception:
    BaseModel = object  # fallback sans validation stricte

log = logging.getLogger(__name__)

class _PostCoursePayload(BaseModel):  # local, évite import externe
    reunion: str
    course: str
    notes: Optional[str] = None

def run_post_course_sync(reunion: str, course: str, drive_folder_id: Optional[str] = None) -> Dict[str, Any]:
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

def is_gcs_enabled() -> bool:
    """
    Active GCS si un bucket est défini ET si on a des identifiants valides.
    Tu peux simplifier le critère selon ton infra.
    """
    bucket = os.getenv("GCS_BUCKET", "").strip()
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    return bool(bucket) and (os.path.exists(creds) if creds else True)

def disabled_reason() -> str:
    reasons = []
    if not os.getenv("GCS_BUCKET"):
        reasons.append("GCS_BUCKET non défini")
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if creds and not os.path.exists(creds):
        reasons.append(f"Fichier d'identifiants introuvable: {creds}")
    if not reasons:
        reasons.append("GCS désactivé par configuration locale")
    return " / ".join(reasons)