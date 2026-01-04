# Matrice de Tests

Ce document dresse l'inventaire des composants du système, les risques associés, et la stratégie de test pour assurer la qualité et la non-régression.

| Composant | Risque Associé | Tests Existants (Couverture) | Tests Manquants | KPI Cible | Effort | Priorité |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **API Publique (/api/pronostics)** | **Élevé** - Contrat de données, performance, disponibilité. | Schéma validé, cache ETag, cas vides. (84% dans `service.py`) | Tests de charge, validation détaillée des contenus mixtes (plan+résultats). | Latence < 500ms, Taux erreur < 0.1% | Moyen | Haute |
| **UI (/pronostics)** | **Moyen** - Expérience utilisateur, régression visuelle. | Présence du conteneur principal et appel API. (`test_ui.py`) | Validation du rendu de la grille de courses, gestion des erreurs JS. | LCP < 2s, 0 erreur JS console | Faible | Faible |
| **Endpoints Sécurisés (/schedule, /ops/\*)** | **Critique** - Contournement d'autorisation. | Tests d'API Key et OIDC token présents. (`test_api_security.py`) | Scénarios avec clés invalides ou expirées, vérification des logs d'audit. | 100% des endpoints testés | Faible | Haute |
| **Pipeline d'Analyse (pipeline_run.py)** | **Très Élevé** - Cœur du métier, impact direct sur les décisions. | Couverture logique principale excellente (96%). | Tests sur les cas limites de données (partants manquants, cotes nulles). | Couverture > 98% | Moyen | Haute |
| **Persistance (firestore_client.py)** | **Moyen** - Intégrité des données, performance des requêtes. | Couverture CRUD complète (100%). | Tests de concurrence (simulés), comportement avec documents malformés. | Couverture 100% | Faible | Faible |
| **Scrapers (scrapers/, stats_provider.py)** | **Élevé** - Fragilité face aux changements externes, parsing. | `boturfers` et `geny` bien couverts (95%), `zeturf` (100%). `stats_provider` à 77%. | Fixtures HTML pour tous les cas (erreurs, variations), tests de détection de changement de structure. | Couverture > 90% par scraper | Élevé | Haute |
| **Scheduler (scheduler.py)** | **Moyen** - Fiabilité de la création des tâches Cloud Tasks. | Couverture complète (100%) des scénarios (dry-run, force, erreurs). | Test d'idempotence pour la re-création de tâches. | Couverture 100% | Faible | Moyenne |
| **Gestion de l'environnement (config/env_utils.py)** | **Élevé** - Risque de mauvaise configuration en production. | Comportement `fail-fast` testé. | Scénarios de fallback et de surcharge de variables. | Couverture 100% | Faible | Moyenne |