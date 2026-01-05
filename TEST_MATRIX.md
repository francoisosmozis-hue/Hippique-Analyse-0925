# Matrice de Tests

| Composant | Risque | Tests existants | Tests manquants | KPI | Effort | Priorité |
|---|---|---|---|---|---|---|
| **API Publique** | | | | | | |
| `/api/pronostics` | Moyen | `test_api_endpoints.py` | Tests de charge, fuzzing sur les dates | Latence < 500ms | Moyen | 2 |
| **UI** | | | | | | |
| `/pronostics` | Faible | `test_service.py` | Tests e2e avec un vrai navigateur | Taux d'erreur JS < 0.1% | Elevé | 3 |
| **Endpoints Sensibles** | | | | | | |
| `/schedule` | Elevé | `test_api_security.py` | Test de non-régression sur l'authentification | 100% des accès non-authentifiés rejetés | Faible | 1 |
| **Pipeline d'Analyse** | | | | | | |
| `analysis_pipeline.py` | Faible | `test_analysis_pipeline_extended.py` | Tests sur des snapshots corrompus | >80% | Faible | 1 |
| **Persistance** | | | | | | |
| `firestore_client.py` | Faible | `test_firestore_client.py` | Tests sur les comportements "collection vide" | >80% | Faible | 1 |
| **Scrapers** | | | | | | |
| `scrapers/` | Moyen | `test_scraper_*.py` | Tests de parsing sur des fixtures HTML cassées | >80% | Moyen | 2 |
| **Scheduler** | | | | | | |
| `scheduler.py` | Moyen | `test_scheduler.py` | Scénarios de défaillance de Cloud Tasks | >80% | Moyen | 2 |
| **Gestion de l'environnement** | | | | | | |
| `config.py` | Elevé | `test_env_utils.py` | Test "fail-fast" en production | 100% | Faible | 1 |
