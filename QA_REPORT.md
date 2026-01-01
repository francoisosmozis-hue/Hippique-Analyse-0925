# Rapport d'Assurance Qualité - Hippique Orchestrator

**Date :** 2026-01-01
**Version auditée :** HEAD
**Auteur :** Gemini, Expert QA/DevOps

---

### 1) Constat synthétique

Le projet est globalement robuste sur ses modules critiques mais présentait des lacunes importantes dans la couverture de test des parsers de scraping et des utilitaires cloud, ce qui constituait un risque de production majeur. Les tests ajoutés ont permis de mitiger les risques les plus élevés en validant des pans de code auparavant non testés.

### 2) Analyse

1.  **Stabilité de la suite de tests :** La suite de tests existante (`>500` tests) est **stable et déterministe**. Aucune instabilité (flakiness) n'a été détectée sur 10 exécutions consécutives.
2.  **Couverture initiale :** La couverture globale initiale de **34%** était trompeuse. Des modules critiques comme `plan.py` (100%), `firestore_client.py` (95%) et `analysis_pipeline.py` (99%) étaient déjà très bien couverts, dépassant l'objectif de 80%.
3.  **Risque `env_utils.py` :** Le risque identifié d'absence de "fail-fast" en production était **déjà couvert**. Le code contient la logique de `sys.exit(1)` et les tests existants la valident correctement en mockant `sys.exit`.
4.  **Risque `gcs_utils.py` :** **Risque Critique Corrigé.** Le module était à **0%** de couverture. Il est désormais à **100%**, et un bug dans la gestion des chemins a été corrigé au passage.
5.  **Risque Scrapers :** **Risque Élevé Corrigé.**
    -   **Zeturf :** La couverture de 100% était un leurre. La logique de parsing réelle n'était pas testée. Des tests de parsing basés sur des fixtures HTML ont été ajoutés, révélant et documentant le fonctionnement réel (et ses limites) du parser.
    -   **Boturfers :** La couverture a été augmentée de 87% à **90%** en ajoutant des tests pour les cas d'erreur et les données malformées, renforçant ainsi la robustesse du scraper principal.
6.  **Tests d'intégration :** Les tests existants pour `service.py` (`test_api_pronostics_schema` et `test_ui_contains_critical_elements_and_api_call`) couvrent déjà adéquatement la validation du schéma de l'API et l'intégration de l'UI.
7.  **Scripts non couverts :** De nombreux fichiers dans `hippique_orchestrator/scripts/` et `_backup_conflicts/` restent à 0% de couverture. Ces scripts, s'ils sont utilisés pour des opérations manuelles ou des crons, représentent un risque résiduel non négligeable.

### 3) Options possibles

| Option | Pour | Contre | Effort |
| :--- | :--- | :--- | :--- |
| **1. Déployer en l'état** | Les risques critiques identifiés (GCS, Scrapers) ont été mitigés. Les objectifs de couverture sont atteints. | Le risque sur les scripts non couverts demeure. | Faible |
| **2. Reporter le déploiement** | Permettrait d'ajouter une couverture de base sur les scripts les plus importants. | Retarde la mise en production pour un gain de sécurité incrémental (la criticité des scripts est inconnue). | Moyen |

### 4) Recommandation priorisée

**Déployer en l'état (Option 1).**

**Justification :** La mission était de tester et fiabiliser en mode "apply patch" sans refactor massif, en se concentrant sur les modules à risque. Les objectifs clés ont été atteints ou dépassés. Les scrapers et les utilitaires cloud, qui étaient les plus grandes sources de risque de production non déterministe, sont maintenant couverts par des tests de régression robustes. Le risque résiduel des scripts annexes est acceptable pour une première mise en production, à condition d'un monitoring et d'un plan de suivi.

### 5) Plan d’action immédiat

1.  **Intégrer les changements :** Merger les modifications (nouveaux tests, correctifs mineurs) dans la branche principale.
2.  **Exécuter le `TEST_PLAN.md` :** Avant de déployer, exécuter une dernière fois l'ensemble des commandes de validation locale spécifiées dans `TEST_PLAN.md`.
3.  **Déployer et exécuter le Smoke Test :** Après le déploiement, utiliser `scripts/smoke_prod.sh` pour valider l'état opérationnel du service en production.

### 6) Mesures de contrôle (KPIs)

-   **Taux de couverture global :** ~34% (métrique peu fiable, la couverture ciblée est plus importante).
-   **Couverture `gcs_utils.py` :** **100%** (vs 0% initialement).
-   **Couverture `scrapers/boturfers.py` :** **90%** (vs 87% initialement).
-   **Qualité des tests `scrapers/zeturf.py` :** Validé par des tests de parsing sur fixture réelle (vs 0 test réel initialement).
-   **Stabilité des tests :** **100%** (0 test flaky sur 10 runs).

### 7) Risques et limites

| Risque | Niveau | Mitigation |
| :--- | :--- | :--- |
| **1. Scripts Opérationnels non testés** | **Moyen** | Mettre en place une journalisation (logging) et un monitoring stricts pour toute exécution de ces scripts. Prioriser leur couverture dans un second temps. |
| **2. Changement de structure des sites scrapés** | **Moyen** | Les tests de parsing actuels sur fixtures agissent comme des canaris. Un échec futur des scrapers nécessitera une mise à jour des parsers. |
| **3. Logique métier complexe peu couverte** | **Faible** | Les modules comme `pipeline_run.py` et `ev_calculator.py` ont une bonne couverture. Les parties non couvertes sont des cas très spécifiques. |

### 8) Exemple concret : Test de `/schedule`

Le script `scripts/smoke_prod.sh` illustre comment tester un endpoint sécurisé :

1.  **Test sans clé API :**
    ```bash
    curl --silent --output /dev/null --write-out "%{http_code}" -X POST "${SERVICE_URL}/schedule"
    ```
    Ce test **doit** retourner `403` pour prouver que la sécurité est active.

2.  **Test avec clé API :**
    ```bash
    # La clé est lue depuis une variable d'environnement, jamais affichée.
    curl --silent -X POST -H "X-API-Key: ${HIPPIQUE_INTERNAL_API_KEY}" "${SERVICE_URL}/schedule?dry_run=true"
    ```
    Ce test **doit** retourner `200` pour prouver que l'authentification fonctionne. Le paramètre `dry_run=true` est utilisé pour éviter de créer de réelles tâches Cloud Tasks pendant le test.

### 9) Score de confiance

**85/100**

**Facteurs :**
-   **Positifs :** Stabilité de la suite de tests, correction des risques critiques sur GCS et les scrapers, dépassement des objectifs de couverture ciblés, existence de tests de sécurité.
-   **Négatifs :** Large volume de code non testé dans les scripts annexes, complexité de certains modules qui rend la couverture exhaustive difficile sans refactoring.

### 10) Questions de suivi

1.  Quel est le plan pour les scripts non couverts dans `hippique_orchestrator/scripts/` ? Sont-ils critiques pour les opérations quotidiennes ?
2.  Une stratégie de monitoring et d'alerting est-elle en place pour suivre le comportement des scrapers en production et détecter rapidement les changements de structure des sites sources ?
