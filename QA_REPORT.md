# Rapport de Test et de Qualité (QA_REPORT.md)

## 1. Constat Synthétique

Le projet `hippique-orchestrator` est globalement robuste, avec une suite de tests unitaires solide et déterministe. Les modules critiques présentent une excellente couverture, mais un risque subsiste au niveau de la robustesse des scrapers et de la couverture des scripts opérationnels.

## 2. Analyse

1.  **Santé de la Suite de Tests :** **Excellente**. 100% des 788 tests passent de manière reproductible. Aucun test "flaky" n'a été détecté après 10 exécutions consécutives.
2.  **Couverture des Modules Critiques :** **Très Bonne**. Les objectifs de couverture ont été atteints et dépassés :
    *   `plan.py`: **100%**
    *   `firestore_client.py`: **100%** (après correction d'un bug logique et ajout de tests)
    *   `analysis_pipeline.py`: **99%**
3.  **Qualité des Tests Scrapers :** **Moyenne**. Bien que la couverture soit élevée (95-100%), les tests ne validaient que le "happy path". Des tests de robustesse ont été ajoutés pour simuler des changements de structure HTML, prouvant que le scraper gère désormais ces cas avec des avertissements clairs au lieu de planter.
4.  **Gestion de l'Environnement (Fail-Fast) :** **Bonne**. Le risque de "configuration silencieuse" en production est bien géré. Le code contient une logique de "fail-fast" (`sys.exit`) qui est correctement validée par les tests existants (`test_get_env_required_missing_in_prod_exits`).
5.  **Sécurité des Endpoints :** **Bonne**. Les endpoints sensibles (`/schedule`, `/ops/*`, `/tasks/*`) sont protégés par une authentification (API Key ou OIDC) et les tests existants valident correctement les cas de refus (401/403). Le `smoke_prod.sh` permet de valider le scénario nominal en production.
6.  **Couverture des Scripts (`/scripts`) :** **Faible**. De nombreux scripts opérationnels ont une couverture de 0%. Ces scripts (ex: `backup_restore.py`, `monitor_roi.py`) représentent un risque opérationnel car ils pourraient échouer en production sans avertissement.
7.  **Tests d'Intégration :** **Bons**. Les tests `TestClient` existants valident adéquatement la stabilité du schéma de `/api/pronostics` et le rendu de base de l'UI `/pronostics`.
8.  **Documentation de Test :** **Créée**. Les fichiers `TEST_MATRIX.md` et `TEST_PLAN.md` ont été créés pour formaliser la stratégie de test et les procédures de validation.

## 3. Options Possibles

| Option                                      | Pour                                                                                                | Contre                                                                                            | Effort | 
| ------------------------------------------- | :-------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------ | ------ | 
| **1. Mettre en production (Acceptable)**    | Le cœur du métier est très bien testé. Les risques immédiats (scrapers, fail-fast) sont maîtrisés.    | Le manque de couverture sur les scripts opérationnels laisse une "dette" de test à gérer.           | Faible | 
| **2. Renforcer la couverture des scripts**  | Élimine le risque opérationnel lié aux scripts non testés. Améliore la maintenabilité à long terme. | Tâche potentiellement chronophage, qui peut retarder la mise en production sans impacter le produit | Moyen  | 
| **3. Investir dans des tests E2E complets** | Simulerait le parcours utilisateur de bout en bout de manière plus réaliste.                           | Complexe à maintenir, "flaky", et contraire à la stratégie de se baser sur des tests unitaires/mockés. | Élevé  | 

## 4. Recommandation Priorisée

**Option 1 : Mettre en production.**

**Justification :** Le niveau de qualité actuel du cœur de l'application est suffisant pour une mise in production. Les risques les plus critiques identifiés dans la demande (robustesse des scrapers, "fail-fast" de la configuration) ont été couverts. La couverture de 100% sur `plan.py` et `firestore_client.py` et 99% sur `analysis_pipeline.py` garantit une grande fiabilité du pipeline d'analyse. Les risques restants (scripts non couverts) sont de nature opérationnelle et peuvent être mitigés par une surveillance accrue post-déploiement et traités dans un second temps.

## 5. Plan d’Action Immédiat

1.  **Merge des Artefacts de Test :** Intégrer `TEST_MATRIX.md`, `TEST_PLAN.md`, `scripts/smoke_prod.sh` et les nouveaux tests (`test_firestore_client_extended.py`, `test_scraper_boturfers_robustness.py`, `test_plan_extended.py`) à la branche principale.
2.  **Déploiement en Production :** Procéder au déploiement sur l'environnement Cloud Run.
3.  **Exécution du Smoke Test :** Exécuter `scripts/smoke_prod.sh` sur l'environnement de production pour valider l'état opérationnel du service.

## 6. Mesures de Contrôle (KPIs)

*   **Taux de succès des tests :** 100% (788/788)
*   **Couverture globale :** ~64%
*   **Couverture `plan.py` :** 100%
*   **Couverture `firestore_client.py` :** 100%
*   **Couverture `analysis_pipeline.py` :** 99%
*   **Couverture `scrapers/boturfers.py` :** 95%

## 7. Risques et Limites

1.  **Scripts Opérationnels non testés (Élevé) :** Des scripts dans le répertoire `/scripts` pourraient échouer en production.
    *   **Mitigation :** Mettre en place une surveillance et des alertes sur l'exécution de ces scripts. Prioriser leur couverture dans le prochain cycle de développement.
2.  **Changements de Structure HTML (Moyen) :** Les scrapers restent sensibles à des changements majeurs sur les sites sources, même avec les tests de robustesse.
    *   **Mitigation :** Mettre en place un monitoring "canary" qui exécute les scrapers à intervalle régulier et alerte en cas de baisse du nombre de courses/runners extraits.
3.  **Dépendances Externes (Faible) :** Les tests reposent sur des mocks pour les services externes (Firestore, Cloud Tasks). Un changement d'API de ces services pourrait casser l'application.
    *   **Mitigation :** Maintenir les dépendances à jour et exécuter périodiquement des tests d'intégration sur un environnement de "staging".

## 8. Exemple Concret : Test de `/schedule`

Le test de l'endpoint `/schedule` illustre la stratégie de sécurité :

*   **Test Unitaire (sans secret) :** `tests/test_api_security.py::test_api_key_authentication` utilise `mocker` pour simuler `REQUIRE_AUTH=True`. Il vérifie qu'un appel sans `X-API-KEY` retourne bien une erreur 403, sans jamais utiliser de vraie clé.
*   **Smoke Test (avec secret) :** Le script `scripts/smoke_prod.sh` lit la vraie clé depuis la variable d'environnement `HIPPIQUE_INTERNAL_API_KEY` (qui n'est pas versionnée). Il exécute un `curl` avec cette clé pour valider le comportement en conditions réelles, sans jamais afficher la clé dans les logs.

```bash
# Extrait de smoke_prod.sh
API_KEY="${HIPPIQUE_INTERNAL_API_KEY:-}"
# ...
assert_status "${URL_PROD}/schedule" 403 "-X POST" "/schedule (sans API Key)"
# ...
assert_status "${URL_PROD}/schedule" 200 "-X POST -H \"X-API-KEY: ${API_KEY}\"" "/schedule (avec API Key)"
```

## 9. Score de Confiance

**85/100**

*   **Facteurs positifs :** Suite de tests très solide sur le cœur de métier, pas de tests "flaky", bonne gestion des dépendances via les mocks.
*   **Facteurs négatifs :** Faible couverture des scripts opérationnels, qui constitue une zone d'ombre.

## 10. Questions de Suivi

1.  Quel est le niveau de criticité et la fréquence d'utilisation des scripts dans le répertoire `hippique_orchestrator/scripts/` ? Cela aidera à prioriser leur couverture de test.
2.  Un environnement de "staging" est-il disponible pour exécuter des tests d'intégration avec de vrais services Google Cloud avant de déployer en production ?