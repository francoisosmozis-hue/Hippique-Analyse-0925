from __future__ import annotations

from pathlib import Path

from google.cloud import storage

from src.config.config import config
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)


def upload_artifacts(rc_dir: Path, artifacts: list[str]) -> None:
    """
    Upload les artefacts vers GCS (si configuré).

    Args:
        rc_dir: Répertoire data/R1C3/
        artifacts: Liste de chemins d'artefacts
    """
    if not config.gcs_bucket:
        return

    try:
        client = storage.Client()
        bucket = client.bucket(config.gcs_bucket)

        for artifact_path in artifacts:
            local_file = Path(artifact_path)
            if not local_file.exists():
                continue

            # GCS path: {prefix}/YYYY-MM-DD/R1C3/filename
            gcs_path = f"{config.gcs_prefix}/{local_file.parent.name}/{local_file.name}"

            blob = bucket.blob(gcs_path)
            blob.upload_from_filename(str(local_file))

            logger.debug(f"Uploaded {artifact_path} → gs://{config.gcs_bucket}/{gcs_path}")

        logger.info(f"Uploaded {len(artifacts)} artifacts to GCS")

    except Exception as e:
        logger.error(f"Failed to upload artifacts to GCS: {e}", exc_info=e)
