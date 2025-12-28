import logging
import sys

from google.cloud import firestore

# Set up logging to see output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Replace 'your-project-id' with the actual project ID
PROJECT_ID = "analyse-hippique"  # From context

# Initialize Firestore client
try:
    db = firestore.Client(project=PROJECT_ID)
    logger.info(f"Firestore client initialized for project: {PROJECT_ID}")
except Exception as e:
    logger.error(f"Failed to initialize Firestore client: {e}")
    sys.exit(1)

date_prefix = "2025-12-07"
races_ref = db.collection("races")

query = (
    races_ref.where(
        firestore.FieldPath.document_id(), ">=", date_prefix
    ).where(  # <-- Using firestore.FieldPath
        firestore.FieldPath.document_id(), "<", date_prefix + "\uf8ff"
    )  # <-- Using firestore.FieldPath
)

docs_found = 0
tickets_found = 0

logger.info(f"Querying Firestore for races with ID starting with '{date_prefix}'...")

for doc in query.stream():
    docs_found += 1
    race_data = doc.to_dict()
    logger.info(f"  Found document: {doc.id}")
    analysis = race_data.get("tickets_analysis")
    if analysis and analysis.get("tickets"):
        tickets_found += 1
        logger.info(f"    - Contains tickets: {len(analysis.get('tickets'))}")
    else:
        logger.info("    - No tickets found in 'tickets_analysis' or 'tickets' is empty.")

logger.info(f"--- Summary for {date_prefix} ---")
logger.info(f"Total documents found: {docs_found}")
logger.info(f"Documents with tickets: {tickets_found}")

if docs_found == 0:
    logger.warning(
        f"No race documents found for {date_prefix}. The pipeline is likely not populating data."
    )
elif tickets_found == 0:
    logger.warning(
        (
            "No race documents found with tickets for %s. Check ticket "
            "generation/saving logic."
        ),
        date_prefix,
    )
else:
    logger.info(
        f"Data found for {date_prefix}. Issue might be in API filtering or front-end display."
    )
