import traceback

from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.scheduler import get_tasks_client

logger = get_logger(__name__)


def main():
    """
    Tente d'initialiser le client Cloud Tasks et de loguer le résultat.
    """
    logger.info("Début du script de débogage du client Tasks...")
    print("PRINT: Début du script de débogage du client Tasks...")

    try:
        client = get_tasks_client()
        logger.info(f"Client Cloud Tasks initialisé avec succès : {client}")
        print(f"PRINT: Client Cloud Tasks initialisé avec succès : {client}")

        # Tentative d'une opération simple (lister les queues)
        config = get_config()
        parent = f"projects/{config.PROJECT_ID}/locations/{config.REGION}"

        logger.info(f"Tentative de lister les queues dans {parent}...")
        print(f"PRINT: Tentative de lister les queues dans {parent}...")

        queues = client.list_queues(parent=parent)
        count = 0
        for queue in queues:
            logger.info(f"Queue trouvée : {queue.name}")
            print(f"PRINT: Queue trouvée : {queue.name}")
            count += 1

        logger.info(f"{count} queue(s) trouvée(s).")
        print(f"PRINT: {count} queue(s) trouvée(s).")
        logger.info("Le client Tasks semble fonctionner correctement.")
        print("PRINT: Le client Tasks semble fonctionner correctement.")

    except Exception as e:
        logger.error(
            f"Une erreur est survenue lors de l'initialisation ou de l'utilisation du client Tasks : {e}",
            exc_info=True,
        )
        print(f"PRINT: Une erreur est survenue : {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
