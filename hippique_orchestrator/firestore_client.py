"""Firestore client for saving and retrieving race data."""

from __future__ import annotations

from typing import Any

from google.cloud import firestore

from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)

_firestore_client = None


def _get_firestore_client(project_id: str | None = None):
    """
    Returns a Firestore client, initializing it if necessary.
    Explicitly uses the provided project_id.
    """
    global _firestore_client
    if _firestore_client is None:
        try:
            # Explicitly pass the project_id to the client constructor
            _firestore_client = firestore.Client(project=project_id)
            logger.info(f"Firestore client initialized successfully for project '{project_id}'.")
        except Exception as e:
            logger.error(f"Failed to initialize Firestore client for project '{project_id}': {e}", exc_info=e)
            return None
    return _firestore_client


def is_firestore_enabled() -> bool:
    """Check if Firestore is configured and enabled."""
    return True


def save_race_document(collection: str, document_id: str, data: dict[str, Any]) -> None:
    """
    Saves or overwrites a document in a Firestore collection.
    """
    if not is_firestore_enabled():
        logger.warning("Firestore is not enabled, skipping save.")
        return
    
    config = get_config()
    client = _get_firestore_client(project_id=config.PROJECT_ID)
    if not client:
        logger.error("Firestore client not available, cannot save document.")
        return

    try:
        doc_ref = client.collection(collection).document(document_id)
        doc_ref.set(data)
        logger.info(f"Document {document_id} saved to collection {collection}.")
    except Exception as e:
        logger.error(
            f"Failed to save document {document_id} to {collection}: {e}",
            exc_info=e,
        )


def update_race_document(collection: str, document_id: str, data: dict[str, Any]) -> None:
    """
    Updates a document in a Firestore collection, merging data.
    """
    if not is_firestore_enabled():
        logger.warning("Firestore is not enabled, skipping update.")
        return

    config = get_config()
    client = _get_firestore_client(project_id=config.PROJECT_ID)
    if not client:
        logger.error("Firestore client not available, cannot update document.")
        return

    try:
        doc_ref = client.collection(collection).document(document_id)
        doc_ref.set(data, merge=True)
        logger.info(f"Document {document_id} updated in collection {collection}.")
    except Exception as e:
        logger.error(
            f"Failed to update document {document_id} in {collection}: {e}",
            exc_info=e,
        )


def get_race_document(collection: str, document_id: str) -> dict[str, Any] | None:
    """
    Retrieves a document from a Firestore collection.
    """
    if not is_firestore_enabled():
        logger.warning("Firestore is not enabled, cannot get document.")
        return None

    config = get_config()
    client = _get_firestore_client(project_id=config.PROJECT_ID)
    if not client:
        logger.error("Firestore client not available.")
        return None

    try:
        doc_ref = client.collection(collection).document(document_id)
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        else:
            logger.info(f"Document {document_id} not found in collection {collection}.")
            return None
    except Exception as e:
        logger.error(
            f"Failed to retrieve document {document_id} from {collection}: {e}",
            exc_info=e,
        )
        return None

def get_races_by_date_prefix(date_prefix: str) -> list[dict[str, Any]]:
    """
    Retrieves all race documents from the 'races' collection where the
    document ID starts with the given date_prefix.
    """
    if not is_firestore_enabled():
        logger.warning("Firestore is not enabled, cannot query races.")
        return []

    config = get_config()
    client = _get_firestore_client(project_id=config.PROJECT_ID)
    if not client:
        logger.error("Firestore client not available.")
        return []

    try:
        races_ref = client.collection("races")
        # Firestore "starts with" query for document IDs
        query = (
            races_ref
            .where(firestore.FieldPath.document_id(), ">=", date_prefix)
            .where(firestore.FieldPath.document_id(), "<", date_prefix + "\uf8ff")
        )
        
        docs_stream = query.stream()
        
        races = []
        for doc in docs_stream:
            race_data = doc.to_dict()
            race_data['id'] = doc.id # Add document ID to the dictionary
            races.append(race_data)
            
        logger.info(f"Found {len(races)} races for date prefix {date_prefix}.")
        return races
    except Exception as e:
        logger.error(
            f"Failed to query races by date prefix {date_prefix}: {e}",
            exc_info=e,
        )
        return []

def list_subcollection_documents(collection: str, document_id: str, subcollection: str) -> list[dict[str, Any]]:
    """
    Lists all documents in a subcollection.
    """
    if not is_firestore_enabled():
        logger.warning("Firestore is not enabled, cannot list subcollection.")
        return []

    config = get_config()
    client = _get_firestore_client(project_id=config.PROJECT_ID)
    if not client:
        logger.error("Firestore client not available.")
        return []

    try:
        docs_stream = client.collection(collection).document(document_id).collection(subcollection).stream()
        return [doc.to_dict() for doc in docs_stream]
    except Exception as e:
        logger.error(
            f"Failed to list documents in subcollection {subcollection} for doc {document_id}: {e}",
            exc_info=e,
        )
        return []

