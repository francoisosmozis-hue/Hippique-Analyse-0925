from __future__ import annotations
import os

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