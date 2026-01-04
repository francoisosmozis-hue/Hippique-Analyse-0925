# Matrice de Tests - Projet Hippique Orchestrator

Ce document détaille la stratégie de test par composant, en évaluant les risques et en identifiant les tests manquants.

| Composant | Risque (1-5) | Tests Existants | Tests Manquants | KPI Cible | Effort (H/M/L) | Priorité (H/M/L) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **API Publique (/pronostics)** | 4 | Validation schéma JSON, ETag, cas vide. | - Test de charge simple (robustesse).<br>- Test sur les en-têtes de sécurité (CSP, HSTS). | Stabilité schéma à 100%. | L | M |
| **UI (/pronostics)** | 3 | Présence d'éléments HTML clés, appel API mocké. | - Test de rendu sur une date sans plan.<br>- Validation de l'affichage d'un message d'erreur si l'API échoue. | Taux de régression visuelle < 5%. | L | L |
| **Endpoints Sensibles (ops, tasks)** | 5 | Tests d'authentification (API Key, OIDC) via `TestClient`. | - Scénario `REQUIRE_AUTH=false` pour tous les endpoints.<br>- Test de non-régression sur l'authentification OIDC (Google). | 100% des endpoints sensibles couverts par un test d'auth. | M | H |
| **Pipeline d'Analyse** | 3 | Couverture de 99% sur `analysis_pipeline.py`. Scénarios nominaux et d'erreurs (GCS, snapshot). | - Vérifier la pertinence des tests sur les cas limites (ex: partants > 20).<br>- Test d'intégration avec un `payout_calibration.yaml` vide ou malformé. | Couverture > 98%. | L | L |
| **Persistance (Firestore/GCS)** | 4 | Couverture de 100% sur `firestore_client.py` (mocks). Tests sur `gcs_client.py`. | - Test de comportement "collection vide" ou "bucket vide".<br>- Test de gestion d'erreur fine (permissions, quota).<br>- **Augmenter couverture `gcs_client.py` à >80%.** | Couverture `gcs_client.py` > 80%. | M | M |
| **Scrapers (Boturfers, Zeturf, Geny)** | 5 | Excellente couverture sur les parsers modernes (>95%). | - **Tests de parsing sur fixtures HTML statiques pour chaque scraper (contrat).**<br>- Détection de changement de structure (ex: un sélecteur clé disparaît).<br>- **Isoler et tester `scripts/online_fetch_zeturf.py` (60% cov).** | 100% des parsers validés par fixture. | H | H |
| **Scheduler / Cloud Tasks** | 4 | Couverture de 100% sur `scheduler.py` avec mocks. | - Test du comportement si `SERVICE_URL` est manquant.<br>- Test de la logique de "skip" si une tâche est dans le passé. | Logique de scheduling 100% couverte. | L | M |
| **Gestion de l'Environnement** | 5 | Tests sur `env_utils.py` (warn, required, fail-fast). | - **Formaliser un test qui prouve le fail-fast en PROD vs non-PROD.**<br>- Test du support des alias (ex: `GCP_PROJECT` vs `GOOGLE_CLOUD_PROJECT`). | Comportement "fail-fast" 100% déterministe. | M | H |
| **Scripts Opérationnels** | 5 | Couverture quasi-nulle sur la plupart des scripts. | - **Ajouter des tests unitaires sur les fonctions critiques de `update_excel_planning.py` (>80% cov).**<br>- Ajouter un test de base (parsing args) pour les scripts les plus importants. | Couverture `update_excel_planning.py` > 80%. | H | H |

---

**Légende :**
- **Risque :** 1 (faible) à 5 (critique).
- **KPI Cible :** Métrique mesurable pour valider l'atteinte de l'objectif.
- **Effort :** Estimation de la complexité de mise en place des tests manquants.
- **Priorité :** Ordre dans lequel les tests doivent être développés.
