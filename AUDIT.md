# AUDIT.md - Rapport d'audit hippique-orchestrator

## Causes racines probables (par ordre d'impact)

1.  **(Impact Élevé)** **Échec Silencieux de la Connexion Firestore.**
    - **Description :** Dans `hippique_orchestrator/firestore_client.py`, l'initialisation du client Firestore est entourée d'un `try...except` trop large. Si une exception survient (très probablement un manque de permission IAM `roles/datastore.user` pour le service account), la variable globale `db` est assignée à `None`.
    - **Conséquence :** Toutes les fonctions de lecture/écriture (`get_races_for_date`, `update_race_document`) retournent des valeurs vides ou ne font rien, sans jamais lever d'erreur. Le reste de l'application fonctionne "normalement", mais sans persistance, ce qui explique parfaitement `total_processed=0`.

2.  **(Impact Moyen)** **Logique de Planification Trop Stricte.**
    - **Description :** Dans `hippique_orchestrator/scheduler.py`, la fonction `_calculate_task_schedule` écarte la création d'une tâche Cloud Task si son heure de déclenchement calculée (ex: H-30) est déjà dans le passé.
    - **Conséquence :** Si le job Cloud Scheduler qui appelle `/schedule` s'exécute avec quelques minutes de retard, aucune tâche n'est créée pour les courses imminentes, et donc aucun traitement n'est lancé. L'échec est silencieux.

3.  **(Impact Faible)** **Routes UI Legacy Non Enregistrées.**
    - **Description :** Les routes `GET /pronostics/ui` et `GET /api/pronostics/ui` ne sont pas déclarées dans le routeur FastAPI de `hippique_orchestrator/service.py`.
    - **Conséquence :** Provoque les erreurs 404 observées.

## Fichiers Impliqués

-   `hippique_orchestrator/firestore_client.py`: **Point central de l'échec silencieux.**
-   `hippique_orchestrator/scheduler.py`: Logique de création des tâches qui peut échouer silencieusement.
-   `hippique_orchestrator/service.py`: Déclaration des routes, où manquent les redirections legacy.
-   `hippique_orchestrator/plan.py`: Fournit le plan de courses initial, qui est correct, mais dont les statuts ne sont jamais mis à jour.

## "Proof Points" (Points de Vérification)

-   **Variable `db`:** La variable globale `db` dans `firestore_client.py` ne devrait jamais être `None` après l'initialisation. Un log critique est nécessaire si l'instanciation échoue.
-   **Logs de Démarrage :** Le service devrait loguer une erreur fatale et s'arrêter s'il ne peut pas se connecter à Firestore. Actuellement, il démarre silencieusement.
-   **Endpoint `/ops/status` (à créer) :** Doit exposer le nombre de documents dans Firestore. Si ce nombre est 0 alors que `total_in_plan > 0`, le problème de connexion est confirmé.
-   **Endpoint `/schedule` :** Devrait loguer explicitement le nombre de tâches créées. Si ce nombre est 0, cela pointe vers un problème de timing dans la planification.
