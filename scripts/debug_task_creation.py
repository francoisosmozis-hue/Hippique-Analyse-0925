import os
from google.cloud import tasks_v2
from google.api_core import exceptions as gcp_exceptions

# Paramètres confirmés à l'étape 1
PROJECT_ID = "analyse-hippique"
LOCATION = "europe-west1"
QUEUE_ID = "hippique-tasks-v2"
# Cible inoffensive pour le test
TARGET_URL = "https://hippique-orchestrator-1084663881709.europe-west1.run.app/health"

def main():
    """Tente de créer une unique tâche Cloud Task."""
    try:
        client = tasks_v2.CloudTasksClient()

        # Construction du chemin complet de la queue
        queue_path = client.queue_path(PROJECT_ID, LOCATION, QUEUE_ID)
        print(f"--- Tentative de création de tâche dans la queue : {queue_path} ---")

        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.GET,
                "url": TARGET_URL,
            }
        }

        response = client.create_task(parent=queue_path, task=task)
        print(f"--- SUCCÈS ! Tâche créée : {response.name} ---")

    except gcp_exceptions.NotFound as e:
        print(f"--- ÉCHEC avec erreur 404 Not Found ---")
        print(f"Détails de l'erreur: {e}")
    except Exception as e:
        print(f"--- ÉCHEC avec une autre erreur ---")
        print(f"Type d'erreur: {type(e).__name__}")
        print(f"Détails de l'erreur: {e}")

if __name__ == "__main__":
    main()
