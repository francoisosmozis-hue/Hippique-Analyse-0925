# Matrice de Tests et Couverture de Code - hippique-orchestrator

## Objectif

Cette matrice évalue l'état actuel de la couverture de code, identifie les zones à risque et propose une priorisation pour le renforcement des tests, conformément aux objectifs de fiabilité du projet hippique-orchestrator.

## Critères d'Évaluation

-   **Composant**: Nom du module Python ou du script.
-   **Risque**: Évaluation du risque en production si le composant contient des bugs (Critique, Élevé, Moyen, Faible).
-   **Tests existants**: Description succincte des tests déjà en place.
-   **% Couverture (actuelle)**: Pourcentage de couverture du code par les tests unitaires/d'intégration.
-   **Tests manquants/améliorations**: Brève description des lacunes ou opportunités.
-   **KPI Cible**: Objectif de couverture de code ou autre métrique pertinente.
-   **Effort**: Estimation de la charge de travail (Élevé, Moyen, Faible).
-   **Priorité**: Ordre d'importance pour l'amélioration (P1, P2, P3).

---

## Matrice

| Composant                                                                   | Risque    | Tests existants                                           | % Couverture (actuelle) | Tests manquants/améliorations                                                                                     | KPI Cible | Effort | Priorité |
| :-------------------------------------------------------------------------- | :-------- | :-------------------------------------------------------- | :---------------------- | :---------------------------------------------------------------------------------------------------------------- | :-------- | :----- | :------- |
| `hippique_orchestrator/runner.py`                                           | Critique  | Partiel, couvre certains flux d'exécution.                | 66%                     | Cas limites, gestion des erreurs, scénarios d'abstention.                                                         | \>85%     | Moyen  | P1       |
| `hippique_orchestrator/pipeline_run.py`                                     | Critique  | Bon, couvre la majorité du pipeline d'analyse.            | 80%                     | Cas d'erreurs rares, combinaisons de paramètres.                                                                  | \>90%     | Faible | P2       |
| `hippique_orchestrator/ev_calculator.py`                                    | Critique  | Très bon, couvre les calculs financiers.                  | 91%                     | Cas d'arrondis, valeurs extrêmes.                                                                                 | \>95%     | Faible | P2       |
| `hippique_orchestrator/firestore_client.py`                                 | Critique  | Très bon, couvre les opérations CRUD.                     | 95%                     | Gestion des permissions (mockées), comportements de latence.                                                       | \>98%     | Faible | P2       |
| `hippique_orchestrator/scheduler.py`                                        | Élevé     | Couverture complète pour la planification de tâches.      | 100%                    | N/A                                                                                                               | 100%      | N/A    | N/A      |
| `hippique_orchestrator/plan.py`                                             | Élevé     | Couverture complète pour la construction du plan de courses. | 100%                    | N/A                                                                                                               | 100%      | N/A    | N/A      |
| `hippique_orchestrator/scrapers/boturfers.py`                               | Élevé     | Très bon, couvre l'extraction de données.                 | 92%                     | Changements structurels du site, cas de données manquantes/malformées.                                            | \>95%     | Moyen  | P1       |
| `hippique_orchestrator/scrapers/geny.py`                                    | Moyen     | Très bon, couvre l'extraction de données.                 | 96%                     | Changements structurels du site, cas de données manquantes/malformées.                                            | \>98%     | Faible | P2       |
| `hippique_orchestrator/scrapers/zeturf.py`                                  | Bas       | Couverture complète, mais scraper obsolète.             | 100%                    | N/A (à supprimer/archiver)                                                                                        | 100%      | N/A    | N/A      |
| `hippique/utils/dutching.py`                                                | Critique  | Très faible.                                              | 23%                     | Tests unitaires approfondis pour tous les scénarios de dutching, cas limites, zéros, valeurs négatives.           | \>90%     | Élevé  | P1       |
| `hippique_orchestrator/service.py`                                          | Élevé     | Couvre les endpoints principaux (health, pronostics).     | 76%                     | Tous les endpoints, validation des requêtes/réponses, gestion des erreurs, tests de sécurité (auth, rate limiting). | \>90%     | Moyen  | P1       |
| `hippique_orchestrator/logging_io.py`                                       | Moyen     | Couverture faible.                                        | 47%                     | Tests des formats de log, des destinations, des niveaux de gravité.                                               | \>80%     | Moyen  | P3       |
| `hippique_orchestrator/snapshot_manager.py`                                 | Élevé     | Très faible.                                              | 24%                     | Gestion des versions de snapshots, restauration, intégrité des données.                                           | \>85%     | Élevé  | P1       |
| `hippique_orchestrator/stats_provider.py`                                   | Critique  | Couverture moyenne.                                       | 60%                     | Fiabilité de la récupération des stats, gestion des IDs, formats de données.                                      | \>90%     | Moyen  | P1       |
| `hippique_orchestrator/validator_ev.py`                                     | Critique  | Couverture moyenne, mais cruciale.                        | 58%                     | Tous les critères de validation, combinaisons de filtres, seuils dynamiques.                                      | \>95%     | Élevé  | P1       |
| `config/env_utils.py`                                                       | Élevé     | Très bon, mais un cas spécifique demandé.                 | 96%                     | Test spécifique pour `get_env` avec comportement `fail-fast` en prod.                                             | \>98%     | Faible | P2       |
| `hippique_orchestrator/scripts/online_fetch_zeturf.py`                      | Moyen     | Partiel.                                                  | 49%                     | `online_fetch_zeturf` doit être considéré comme obsolète ou être mis à jour pour Boturfers.                       | \>90%     | Élevé  | P3       |
| `hippique_orchestrator/scripts/simulate_ev.py`                              | Critique  | Partiel.                                                  | 71%                     | Intégration avec `ev_calculator`, cas d'erreurs, performance.                                                     | \>90%     | Moyen  | P1       |
| `hippique_orchestrator/scripts/simulate_wrapper.py`                         | Critique  | Bon.                                                      | 79%                     | Cas limites, gestion des exceptions, intégrité du cache.                                                          | \>90%     | Moyen  | P1       |
| `hippique_orchestrator/scripts/snapshot_enricher.py`                        | Élevé     | Aucun.                                                    | 0%                      | Tests complets d'enrichissement, validation des données, cas d'erreurs.                                           | \>90%     | Élevé  | P1       |
| `hippique_orchestrator/scripts/update_excel_planning.py`                    | Élevé     | Très bon, mais doit gérer les nouvelles structures.       | 86%                     | Tests des mises à jour de toutes les colonnes, formats de date/heure, cas d'erreurs d'écriture.                  | \>95%     | Moyen  | P2       |

---

### Scripts utilitaires / Fichiers non-critiques (couverture non prioritaire)

Les fichiers suivants ont une couverture faible ou nulle, mais sont considérés comme des scripts utilitaires, des configurations, ou des modules non directement liés à la logique métier critique pour la production. Leur couverture n'est pas une priorité immédiate sauf si des problèmes spécifiques sont identifiés.

-   `_backup_conflicts/*`: Fichiers de backup, non pertinents pour la couverture active.
-   `check_firestore_data.py` (0%)
-   `debug_task_client.py` (0%)
-   `gunicorn_conf.py` (0%)
-   `main_debug.py` (0%)
-   `setup.py` (0%)
-   `sklearn/*` (0%) - Semble être des restes ou des modules tiers, à confirmer.
-   `trigger_schedule.py` (0%)
-   `hippique_orchestrator/utils/probabilities.py` (78%) - Faible risque.
-   `hippique_orchestrator/api/tasks.py` (88%) - Faible risque.
-   `hippique_orchestrator/auth.py` (83%) - Faible risque.
-   `hippique_orchestrator/data_source.py` (61%) - Risque faible.
-   `hippique_orchestrator/kelly.py` (83%) - Risque faible.
-   `hippique_orchestrator/logging_middleware.py` (82%) - Risque faible.
-   `hippique_orchestrator/logging_utils.py` (89%) - Risque faible.
-   `hippique_orchestrator/post_course_payload.py` (93%) - Risque faible.
-   `hippique_orchestrator/time_utils.py` (69%) - Risque faible.
-   `hippique_orchestrator/scripts/concat_je_month.py` (0%)
-   `hippique_orchestrator/scripts/cron_decider.py` (0%)
-   `hippique_orchestrator/scripts/drive_sync.py` (0%)
-   `hippique_orchestrator/scripts/enrich_requirements.py` (0%)
-   `hippique_orchestrator/scripts/fetch_je_chrono.py` (0%)
-   `hippique_orchestrator/scripts/fetch_je_stats.py` (0%)
-   `hippique_orchestrator/scripts/gcs_utils.py` (0%)
-   `hippique_orchestrator/scripts/guardrails.py` (100%)
-   `hippique_orchestrator/scripts/lint_sources.py` (0%)
-   `hippique_orchestrator/scripts/merge_all_data.py` (0%)
-   `hippique_orchestrator/scripts/monitor_roi.py` (0%)
-   `hippique_orchestrator/scripts/resolve_course_id.py` (59%)
-   `hippique_orchestrator/scripts/restore_from_drive.py` (0%)
-   `hippique_orchestrator/scripts/snapshot_enricher.py` (0%)
-   `hippique_orchestrator/scripts/update_excel_with_results.py` (0%)
-   `hippique_orchestrator/stats_fetcher.py` (0%)
-   `hippique_orchestrator/scripts/p_finale_export.py` (56%)