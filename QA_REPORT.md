# QA & Production Readiness Report: Hippique Orchestrator

**Date:** 2026-01-05
**Author:** Gemini, Senior QA/DevOps Expert
**Verdict:** **NON PRÊT POUR LA PRODUCTION**

---

## 1. Constat Synthétique

Le projet a une base de tests unitaires solide et déterministe, mais une couverture de code très insuffisante sur des modules algorithmiques et d'I/O critiques. Les risques liés à une configuration défaillante en production et à des changements de structure chez les sources de données (scrapers) sont trop élevés pour un déploiement sécurisé.

## 2. Analyse Détaillée

- **Suite de Tests:** La suite de tests existante est robuste, avec 100% de succès sur 10 exécutions consécutives, confirmant l'absence de tests flaky.
- **Couverture de Code:** La couverture globale est de 8%, ce qui est extrêmement bas. Les modules critiques ciblés sont bien en deçà de l'objectif de 80% :
    - `plan.py`: **36%** (Risque: la logique de sélection des courses à jouer peut être erronée).
    - `firestore_client.py`: **41%** (Risque: des erreurs de communication avec la base de données pourraient passer inaperçues).
    - `analysis_pipeline.py`: **15%** (Risque: le cœur de l'analyse des courses, est une boîte noire).
- **Sécurité:** Les endpoints sensibles (`/schedule`, `/ops/run`) sont correctement protégés par une clé API (`X-API-Key`), et les tests de sécurité confirment que l'accès non authentifié est rejeté.
- **Configuration:** Le mécanisme de "fail-fast" pour les variables d'environnement manquantes a été implémenté et testé, réduisant le risque de mauvaise configuration en production.
- **Scrapers:** Les scrapers manquent de tests de robustesse. Un changement de structure sur les sites sources (ex: `boturfers.fr`) casserait la collecte de données sans alerte immédiate.
- **Tests d'Intégration:** Des tests d'intégration de base ont été ajoutés pour valider le schéma de l'API `/api/pronostics` et l'intégrité de l'UI, mais ils ne couvrent pas les scénarios d'erreur.
- **Documentation:** `TEST_MATRIX.md` et `TEST_PLAN.md` ont été créés, fournissant une bonne base pour les futures campagnes de test.
- **Smoke Test:** Le script `scripts/smoke_prod.sh` a été créé pour permettre une validation rapide post-déploiement.

## 3. Options Possibles

| Option                               | Pour                                                                                              | Contre                                                                                             | Effort |
| ------------------------------------ | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ------ |
| **1. Déployer en l'état (NON RECOMMANDÉ)** | Lancer rapidement, obtenir des données réelles.                                                   | Risque élevé de bugs silencieux (mauvais paris, perte de données), maintenance difficile.          | Faible |
| **2. Renforcer les tests (RECOMMANDÉ)** | Augmenter significativement la confiance, réduire les risques de production, faciliter la maintenance. | Nécessite un investissement en temps de développement supplémentaire avant le lancement.            | Moyen  |
| **3. Refactoring + Tests**           | Idéal à long terme pour la maintenabilité.                                                        | Dépasse le cadre "apply patch", effort le plus élevé, retarde le plus le déploiement.                | Elevé  |

## 4. Recommandation Priorisée

**Option 2: Renforcer les tests.**

Il est impératif d'augmenter la couverture de code sur les modules critiques avant tout déploiement en production. Le risque financier et de réputation lié à un système de paris automatisé non fiable est trop important pour être ignoré.

## 5. Plan d'Action Immédiat

1.  **Augmenter la couverture de `plan.py` et `firestore_client.py` > 80%:**
    -   **Livrable:** Tests unitaires couvrant les cas nominaux, les cas limites et les erreurs attendues.
2.  **Créer des tests de parsing pour les scrapers:**
    -   **Livrable:** Utiliser des fixtures HTML locales (`tests/fixtures/`) pour tester la logique d'extraction des données de chaque scraper. Les tests doivent valider le parsing correct et la gestion des erreurs (ex: structure de page modifiée).
3.  **Augmenter la couverture de `analysis_pipeline.py` > 50%:**
    -   **Livrable:** Ajouter des tests d'intégration qui simulent des données d'entrée et valident les décisions de sortie du pipeline (`play`, `abstain`, `error`).

## 6. Mesures de Contrôle (KPIs)

- **Couverture de code globale:** > 50%
- **Couverture `plan.py`:** > 80%
- **Couverture `firestore_client.py`:** > 80%
- **Couverture `analysis_pipeline.py`:** > 50%
- **Taux de passage des tests:** 100%

## 7. Risques et Limites

1.  **Dépendance aux sites externes (Elevé):** Même avec des tests de parsing, une modification du HTML des sites de scraping entraînera une défaillance.
    -   **Mitigation:** Mettre en place un monitoring "canary" qui exécute les scrapers périodiquement et alerte si aucune donnée n'est retournée.
2.  **Logique métier complexe non testée (Elevé):** La faible couverture de `analysis_pipeline.py` et `ev_calculator.py` signifie que la logique de décision de pari n'est pas validée.
    -   **Mitigation:** Suivre le plan d'action pour augmenter la couverture.
3.  **Performance en charge (Moyen):** Les tests actuels ne valident pas le comportement du service sous une charge importante.
    -   **Mitigation:** Des tests de charge pourraient être envisagés dans un second temps, après la mise en production initiale.

## 8. Exemple Concret: Validation du /schedule

Le script `scripts/smoke_prod.sh` illustre comment valider la sécurité de l'endpoint `/schedule`.

**Sans clé API (accès interdit):**
```bash
$ curl -s -o /dev/null -w "%{http_code}" -X POST https://<your-url>/schedule
403
```
*Le statut 403 (Forbidden) confirme que l'endpoint est protégé.*

**Avec clé API (accès autorisé):**
```bash
$ export HIPPIQUE_INTERNAL_API_KEY="votre-cle-secrete"
$ curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "X-API-Key: $HIPPIQUE_INTERNAL_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"dry_run": true}' \
    https://<your-url>/schedule
200
```
*Le statut 200 (OK) confirme que l'accès est autorisé avec une clé valide.*

## 9. Score de Confiance

**35 / 100**

- **Facteurs positifs:** Base de tests unitaires saine et déterministe, sécurité des endpoints vérifiée, "fail-fast" sur la configuration.
- **Facteurs négatifs:** Couverture de code dramatiquement faible sur les modules critiques, absence de tests de robustesse pour les scrapers, logique de décision de pari non validée.

## 10. Questions de Suivi

1.  L'équipe est-elle prête à investir le temps nécessaire pour atteindre les objectifs de couverture de code avant la mise en production ?
2.  Quel est le plan pour le monitoring "canary" des scrapers une fois en production ?
