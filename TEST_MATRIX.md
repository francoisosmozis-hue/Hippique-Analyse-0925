# Matrice de Tests - Hippique Orchestrator

Ce document détaille la stratégie de test pour les composants critiques du projet, en se basant sur l'analyse de couverture et les risques fonctionnels.

| Composant | Risque | Tests Existants (Couverture) | Tests Manquants | KPI Cible | Effort | Priorité |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Scrapers (Critique)**| **Élevé** | `zeturf.py` (25%), `geny.py` (0%), `zoneturf_client.py` (29%). Très insuffisant. | **Parsing HTML via fixtures pour tous les cas.** Gestion des erreurs réseau/HTTP 4xx/5xx. Détection de changement de structure (ex: un sélecteur clé non trouvé). | >80% | **Élevé** | **1** |
| **Utilitaires Cloud** | **Élevé** | `gcs_utils.py` (0%), `firestore_client.py` (81%). Partiel. | `gcs_utils`: **Toute la logique de CRUD est à tester.** `firestore`: gestion des erreurs de connexion/timeout, comportement sur collection vide. | >85% | Moyen | **2** |
| **Cloud Tasks (Scheduler)** | Moyen | `scheduler.py` (72%). Scénarios dry-run/force couverts. | Tests sur les erreurs de création de tâche (permissions, quota). Validation de la charge utile (payload) de la tâche, notamment les `schedule_time`. | >85% | Moyen | **3** |
| **Gestion Env & Config** | Moyen | `env_utils.py` a des tests de base. | **Valider le comportement "fail-fast" en mode prod** (si implémenté). Tester les alias et les valeurs par défaut de `config.py`.| 100% | Faible | **4** |
| **Endpoints Sécurisés** | Faible | Tests OK pour API Key (`/schedule`) et OIDC (`/tasks/run-phase`). | Scénarios de clés invalides/révoquées (via mock). Tester que `REQUIRE_AUTH=false` désactive bien la sécurité. | 100% des cas d'auth couverts | Faible | 5 |
| **Pipeline d'Analyse** | Faible | `analysis_pipeline.py` (89%), `plan.py` (95%). Tests robustes. | Revoir les quelques lignes non couvertes pour des cas rares (erreurs I/O, data malformée). | >90% | Faible | 6 |
| **API Publique** | Faible | Bonnes bases sur les endpoints (`/pronostics`, `/health`). | Tests de charge/stress, fuzzing sur les query params (`date`). Validation du schéma de réponse JSON. | Stabilité à 99.9% | Moyen | 7 |