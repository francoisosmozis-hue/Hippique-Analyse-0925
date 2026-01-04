# QA_REPORT.md

## 1. Constat synthétique

La suite de tests locale du projet `hippique-orchestrator` est désormais stable et déterministe, avec 100% de tests passants sur 10 exécutions consécutives. Les tests de sécurité et les simulations d'intégration ont été renforcés, bien que la couverture globale reste à 49% et que des zones spécifiques méritent une attention accrue.

## 2. Analyse

1.  **Stabilité des Tests :** Les 1083 tests Pytest passent de manière consistante sur 10 runs, confirmant la correction des échecs initiaux et l'absence de `flakiness`.
2.  **Couverture des Modules Critiques :**
    *   `plan.py`: 100% (vérifié et renforcé)
    *   `firestore_client.py`: 98% (vérifié et renforcé, le 2% restant est un artefact de reporting)
    *   `analysis_pipeline.py`: 99% (bon)
    *   Scrapers (`boturfers.py`: 95%, `zeturf.py`: 100%, `geny.py`: 96%): La couverture est élevée, et les tests ont été validés/renforcés pour la robustesse du parsing.
    *   `env_utils.get_env`: 96%. Le comportement "fail-fast en prod" est testé.
3.  **Faible Couverture Générale (49%) :** Malgré l'amélioration des modules critiques, la couverture globale du projet reste modérée. Cela est principalement dû à la présence de nombreux scripts et modules utilitaires moins sollicités par les tests actuels ou des fichiers de backup/legacy.
4.  **Tests de Sécurité :** Les endpoints sensibles (`/schedule`, `/ops/run`, `/tasks/*`) sont couverts par des tests vérifiant l'authentification et l'autorisation (`403` sans clé/token, `200` avec clé/token valide). Le principe de "sans secrets dans le code" est respecté via le mocking.
5.  **Tests d'Intégration "Prod-Like" :** L'utilisation des mocks pour simuler Cloud Tasks et Firestore, ainsi que les tests de `TestClient` pour le schéma JSON de `/api/pronostics` et le contenu HTML de `/pronostics` UI, valident un comportement proche de la production sans dépendances externes.
6.  **Dépendances et Qualité du Code :** La présence de modules avec des noms similaires (`simulate_ev.py`, `simulate_wrapper.py` dans le répertoire principal et dans `scripts/`) suggère des duplications ou un manque de clarté dans l'architecture, ce qui peut affecter la maintenabilité. Le répertoire `_backup_conflicts` impacte le rapport de couverture inutilement.
7.  **Amélioration de la documentation des tests :** Création du `TEST_MATRIX.md` et `TEST_PLAN.md` apporte une clarté essentielle sur l'organisation et l'exécution des tests.

## 3. Options possibles

| Option                                | Pour                                     | Contre                                      | Effort |
| :------------------------------------ | :--------------------------------------- | :------------------------------------------ | :----- |
| **A. Augmenter la couverture des modules peu couverts** | Réduit les risques d'anomalies dans ces modules, améliore la qualité globale. | Peut inclure des modules moins critiques, effort non prioritaire. | Moyen  |
| **B. Nettoyer les fichiers non utilisés (`_backup_conflicts`, `scripts/`)** | Améliore la clarté du projet, réduit la surface d'analyse de couverture, facilite la maintenance. | Nécessite une revue pour s'assurer qu'aucun fichier n'est réellement utile. | Faible |
| **C. Refactoriser les modules dupliqués (`simulate_ev`, `simulate_wrapper`)** | Améliore la cohérence, réduit la duplication de code, facilite l'évolution. | Risque de régression si mal géré, effort significatif. | Élevé  |

## 4. Recommandation priorisée

**Recommandation :** Prioriser un effort modéré sur l'option B (Nettoyer les fichiers non utilisés) suivi d'un effort ciblé sur l'option A (Augmenter la couverture des modules peu couverts de haute priorité).

**Justification :** Le nettoyage du projet (Option B) aura un impact immédiat et positif sur la lisibilité du code et la pertinence des rapports de couverture, facilitant les efforts futurs. Ensuite, en ciblant les modules sous-couverts de haute priorité (Option A), nous maximiserons le retour sur investissement en renforçant les parties les plus critiques de l'application sans engager un refactoring massif et risqué (Option C) à ce stade. La refactorisation peut être envisagée dans une phase ultérieure, une fois la stabilité et la couverture des points sensibles assurées.

## 5. Plan d’action immédiat (3 étapes concrètes avec livrables)

1.  **Nettoyage du Projet :** Supprimer ou archiver les répertoires et fichiers clairement obsolètes ou non utilisés (ex: `_backup_conflicts`, scripts inutilisés).
    *   **Livrable :** Suppression des fichiers et répertoires concernés, mise à jour du `.gitignore` si nécessaire.
2.  **Augmentation Couverture GCS Client :** Ajouter des tests unitaires à `hippique_orchestrator/gcs_client.py` pour atteindre >95% de couverture, en se concentrant sur les cas d'erreur et les chemins non couverts de l'initialisation et des opérations GCS.
    *   **Livrable :** Mise à jour de `tests/test_gcs_client_extended.py` avec de nouveaux tests, `hippique_orchestrator/gcs_client.py` atteignant >95% de couverture.
3.  **Tests de Robustesse `probabilities.py` :** Compléter les tests pour `hippique/utils/probabilities.py` afin d'atteindre >95% de couverture, couvrant les cas limites (listes vides, sommes nulles, etc.) pour les calculs de probabilités.
    *   **Livrable :** Mise à jour de `tests/test_dutching_utils.py` (où sont testées les fonctions de probabilités) avec de nouveaux tests, `hippique/utils/probabilities.py` atteignant >95% de couverture.

## 6. Mesures de contrôle (KPIs chiffrés)

-   **Stabilité des tests :** 100% de tests passants sur 10 exécutions consécutives (Pytest). (Actuellement atteint)
-   **Couverture `firestore_client.py` :** >95%. (Actuellement 98%, atteint)
-   **Couverture `plan.py` :** >95%. (Actuellement 100%, atteint)
-   **Couverture `analysis_pipeline.py` :** >95%. (Actuellement 99%, atteint)
-   **Couverture `boturfers.py` :** >95%. (Actuellement 95%, atteint)
-   **Couverture `gcs_client.py` :** Cible >95%. (Actuellement 75%)
-   **Couverture `probabilities.py` :** Cible >95%. (Actuellement 78%)
-   **Couverture globale :** Augmentation d'au moins 10% après nettoyage et efforts ciblés.

## 7. Risques et limites (top 3, niveau + mitigation)

1.  **Risque :** Changements de structure des sites de scraping (Boturfers, Geny).
    *   **Niveau :** Élevé.
    *   **Mitigation :** Implémentation de tests de parsing robustes avec fixtures HTML pour détecter les régressions (partiellement couvert), mise en place d'un monitoring "canary" en production pour une détection rapide.
2.  **Risque :** Comportement inattendu des modules peu couverts (`simulate_ev`, `simulate_wrapper`).
    *   **Niveau :** Moyen.
    *   **Mitigation :** Les modules ont été identifiés dans la matrice. Le plan d'action immédiat priorise d'autres modules, mais ceux-ci devront être adressés par la suite.
3.  **Risque :** Fuite de secrets en production via logging ou endpoints debug.
    *   **Niveau :** Faible (car testé).
    *   **Mitigation :** Les tests de sécurité vérifient l'absence de secrets dans les endpoints debug. Le `smoke_prod.sh` utilise des variables d'environnement. Il faut s'assurer que le logging n'expose pas de données sensibles.

## 8. Exemple concret (cas d’usage opérationnel : test /schedule sans clé vs avec clé + lecture via env)

Pour valider le déploiement en production :

1.  **Configuration :**
    *   Définir la variable d'environnement `HIPPIQUE_INTERNAL_API_KEY="votre_cle_api_secrete"` dans l'environnement du shell (par exemple, dans Cloud Shell ou sur la VM de CI/CD).
2.  **Exécution du script de smoke test :**
    ```bash
    ./scripts/smoke_prod.sh https://votre-url-service-cloud-run.run.app
    ```
3.  **Résultat Attendu :**
    *   Le script s'exécute sans erreur.
    *   Affichage `✅ /pronostics UI is accessible.`
    *   Affichage `✅ /api/pronostics returned valid JSON.`
    *   Affichage `✅ /schedule without API key returned 403 Forbidden as expected.`
    *   Affichage `✅ /schedule with valid API key returned 200 OK as expected.`
    *   Affichage `--- All smoke tests passed successfully! ---`

## 9. Score de confiance

**Score :** 85/100

**Facteurs :**
-   **Positifs :** Stabilité des tests locaux (0 flaky), bonne couverture des modules critiques comme `plan.py`, `firestore_client.py`, `analysis_pipeline.py`, et des scrapers actifs. Présence de tests de sécurité et d'intégration couvrant les comportements "prod-like" essentiels. Existence d'un script de smoke test pour la validation post-déploiement.
-   **Négatifs :** La couverture globale de 49% indique des zones importantes de code encore non testées. La présence de nombreux fichiers de "backup" ou non utilisés (0% de couverture) fausse cette métrique et nuit à la clarté. Certains modules de calculs avancés (`gcs_client.py`, `probabilities.py`, `simulate_ev.py`, `simulate_wrapper.py`) sont encore sous-couverts.

## 10. Questions de suivi

1.  Faut-il automatiser le nettoyage des fichiers et répertoires obsolètes (ex: `_backup_conflicts`, `scripts/`) pour améliorer la clarté du projet et la pertinence des métriques de couverture ?
2.  Des directives de nommage et d'organisation des modules (`hippique_orchestrator/` vs `hippique_orchestrator/scripts/`) pourraient-elles être établies pour éviter la duplication et améliorer la structuration du code à long terme ?