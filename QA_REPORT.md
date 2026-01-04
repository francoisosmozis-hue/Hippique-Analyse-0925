# Rapport d'Audit Qualité et de Tests - Hippique Orchestrator

**Date :** 2026-01-04
**Auteur :** Agent QA/DevOps Gemini
**Verdict :** **Prêt pour la production, avec des réserves critiques.**

---

### 1) Constat Synthétique

La base de code est fonctionnelle et dispose d'une suite de tests locaux déterministe qui passe intégralement. Les modules critiques du service (`plan`, `firestore_client`, `analysis_pipeline`, `scheduler`) sont bien couverts, mais un risque majeur demeure en raison de la couverture quasi nulle des scripts opérationnels annexes, qui sont essentiels au cycle de vie complet du produit.

### 2) Analyse

-   **Points Forts :**
    -   **Stabilité :** La suite de tests existante (>900 tests) est robuste et passe à 100%, sans aucun test "flaky" détecté sur 10 exécutions consécutives.
    -   **Couverture des modules critiques :** Les modules au cœur du service (API, pipeline d'analyse, DB) affichent une excellente couverture (>98%), surpassant l'objectif initial de 80%.
    -   **Sécurité des Endpoints :** Les mécanismes d'authentification (API Key, OIDC) sont en place et leurs tests de non-régression sont fonctionnels, y compris pour le cas où l'authentification est désactivée.
    -   **Robustesse des Scrapers :** Des tests basés sur des fixtures HTML ont été ajoutés pour les scrapers `boturfers` et `zeturf` (via `online_fetch`), garantissant un contrat de parsing et une meilleure détection des régressions.
    -   **Fiabilisation du CI :** Un plan de validation (`TEST_PLAN.md`) et un script de smoke test (`scripts/smoke_prod.sh`) ont été créés pour formaliser et automatiser les contrôles qualité.

-   **Points Faibles et Risques :**
    -   **Scripts Opérationnels non testés :** C'est le **risque principal**. Des scripts comme `update_excel_with_results.py`, `backup_restore.py` et de nombreux autres ont une couverture de code proche de 0%. Une erreur dans ces scripts peut corrompre des données, fausser des rapports ou bloquer des workflows manuels critiques sans alerte préalable.
    -   **Code Legacy :** Le script `scripts/online_fetch_zeturf.py` est un module complexe et vieillissant, difficile à maintenir et à tester. Bien que sa couverture ait été améliorée, il représente une dette technique significative.
    -   **Gestion des Erreurs de Parsing :** Les scrapers loggent des warnings en cas de champ manquant mais ne déclenchent pas d'alerte formelle, ce qui pourrait masquer un changement de structure du site source.

### 3) Options Possibles

| Option | Pour | Contre | Effort |
| :--- | :--- | :--- | :--- |
| **A) Déployer en l'état** | Mise en production rapide. Le service principal est stable. | Risque très élevé sur les opérations annexes (Excel, backup, etc.). Une erreur silencieuse est probable. | **Faible** |
| **B) Ajouter une couverture minimale sur les scripts critiques** | Réduit significativement le risque sur les opérations les plus courantes. Faisable en mode "apply patch". | Ne couvre pas tous les scripts. Reste une dette technique. | **Moyen** |
| **C) Refactoriser/Déprécier les scripts Legacy** | Solution la plus saine à long terme. Élimine la dette technique et simplifie la maintenance. | Interdit par la contrainte "pas de refactor massif". Dépasse le cadre de la mission QA. | **Élevé** |

### 4) Recommandation Priorisée

**Option B : Ajouter une couverture minimale sur les scripts critiques.**

**Justification :** Cette option offre le meilleur compromis entre la vitesse de déploiement et la réduction des risques, tout en respectant la contrainte "apply patch". En ajoutant des tests unitaires sur les fonctions clés de `update_excel_planning.py` et `update_excel_with_results.py`, nous nous assurons que le workflow de suivi des performances, probablement le plus utilisé, est fiable. Cela laisse la porte ouverte à un chantier de refactorisation futur (Option C) tout en sécurisant l'existant.

### 5) Plan d'Action Immédiat

1.  **Augmenter la couverture de `update_excel_planning.py` et `update_excel_with_results.py` > 60%** en ajoutant des tests unitaires sur les fonctions de parsing et de manipulation de données (sans I/O).
2.  **Mettre en place un "canary test" documenté** : un test d'intégration léger qui exécute un scraper sur une fixture HTML et alerte si le nombre de champs extraits change drastiquement, pour détecter les changements de structure des sites sources.
3.  **Auditer et documenter tous les scripts du répertoire `scripts/`** en créant un `README.md` qui décrit leur fonction, leurs inputs/outputs et leur niveau de risque (non testé).

### 6) Mesures de Contrôle

-   **Taux de couverture `update_excel_*.py` :** > 60%
-   **Taux de succès `pytest -q` :** 100%
-   **Taux de succès `scripts/smoke_prod.sh` :** 100%
-   **Nombre de scripts opérationnels documentés :** 100%

### 7) Risques et Limites

1.  **Risque Élevé : Erreur dans un script non priorisé.** Un script non couvert par le plan d'action ci-dessus (ex: `backup_restore.py`) peut échouer en production. *Mitigation : Documentation (plan d'action #3) et exécution manuelle prudente.*
2.  **Risque Moyen : Changement de structure HTML non détecté.** Un site partenaire peut changer son HTML d'une manière que les tests actuels ne détectent pas. *Mitigation : Canary test (plan d'action #2) et monitoring externe.*
3.  **Risque Faible : Régression sur le service principal.** Les modules critiques étant bien testés, le risque est faible mais non nul. *Mitigation : Exécution systématique du `smoke_prod.sh` post-déploiement.*

### 8) Exemple Concret : Test de l'Endpoint `/schedule`

Le script `scripts/smoke_prod.sh` valide la sécurité de l'endpoint `/schedule` :
1.  **Sans clé API :**
    ```bash
    curl -s -o /dev/null -w "%{http_code}" -X POST ... "${PROD_URL}/schedule"
    ```
    Ce test vérifie que le code de statut est `403` (Forbidden), prouvant que l'accès est bien bloqué.
2.  **Avec clé API :**
    ```bash
    curl -s -o /dev/null -w "%{http_code}" -X POST -H "X-API-KEY: ${HIPPIQUE_INTERNAL_API_KEY}" ...
    ```
    Ce test, utilisant une variable d'environnement pour ne jamais exposer la clé, vérifie que le code de statut est `200` (OK), prouvant que l'accès est autorisé avec une clé valide.

### 9) Score de Confiance

**85/100**

-   **Facteurs positifs :** Stabilité de la suite de tests, excellente couverture des modules applicatifs principaux, sécurité des endpoints validée.
-   **Facteurs négatifs :** La dette technique et l'absence de couverture sur les scripts opérationnels représentent un risque non négligeable qui empêche d'atteindre un score > 95.

### 10) Questions de Suivi

1.  Quel est le plan à moyen terme pour les scripts du répertoire `scripts/` ? Doivent-ils être maintenus, refactorisés dans le service principal, ou dépréciés ?
2.  Comment les changements de structure des sites scrapés sont-ils actuellement monitorés, et un système d'alerte formel est-il envisagé ?
