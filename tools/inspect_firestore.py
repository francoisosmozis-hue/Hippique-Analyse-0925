import argparse
import os
import subprocess
from datetime import datetime

from google.cloud import firestore


def inspect_firestore(date_str: str):
    """
    Connects to Firestore and lists documents in the 'races' collection for a specific date.
    """
    project_id = os.environ.get("GCP_PROJECT") or os.environ.get("PROJECT_ID")
    if not project_id:
        raise ValueError(
            "Project ID not found. Please set the GCP_PROJECT or PROJECT_ID environment variable."
        )

    print(f"Connecting to Firestore for project '{project_id}'...")
    db = firestore.Client(project=project_id)

    target_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
    print(f"Fetching documents from 'races' collection for date: {target_date}")

    races_ref = db.collection("races")
    query = races_ref.where("date", "==", target_date)

    try:
        docs = list(query.stream())
    except Exception as e:
        print(f"An error occurred while fetching data: {e}")
        print(
            "\nPlease ensure the Firestore API is enabled and that you have "
            "permissions to read from it."
        )
        return

    if not docs:
        print("No documents found in 'races' collection for the specified date.")
        return

    print(f"Found {len(docs)} documents:")
    for doc in docs:
        data = doc.to_dict()
        race_id = data.get("id", doc.id)
        last_updated = data.get("last_updated", "N/A")
        gpi_decision = data.get("gpi_decision", "N/A")
        num_tickets = len(data.get("tickets", []))

        print(
            f"  - Race ID: {race_id:<10} | "
            f"Last Updated: {last_updated} | "
            f"Decision: {gpi_decision:<20} | "
            f"Tickets: {num_tickets}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect Firestore 'races' collection.")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="The date to inspect, in YYYY-MM-DD format. Defaults to today.",
    )
    args = parser.parse_args()

    # The gcloud CLI sets this, but it's good practice to ensure it for direct script execution
    if "GCP_PROJECT" not in os.environ:
        # Attempt to get project from gcloud config if available
        try:
            project = subprocess.check_output(
                ["gcloud", "config", "get-value", "project"], text=True
            ).strip()
            if project:
                os.environ["GCP_PROJECT"] = project
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass  # gcloud might not be installed or configured

    inspect_firestore(args.date)
