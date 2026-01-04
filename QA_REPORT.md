# Rapport d'Assurance Qualité - Hippique Orchestrator

**Date:** 2026-01-04
**Auteur:** Gemini, Expert QA/DevOps
**Verdict Final:** **Prêt pour Production, avec Risques Maîtrisés (Go Prod Conditionnel)**

---

### 1. Constat Synthétique

Le projet possède une base de tests solide et une logique applicative principale (API, pipeline d'analyse) robuste et bien testée. Les risques critiques identifiés sur les modules d'I/O et de configuration ont été corrigés avec succès, augmentant significativement la fiabilité. Le risque résiduel, jugé acceptable, se concentre sur les scripts manuels non-testés.

### 2. Analyse Approfondie

1.  **Stabilité de la suite de tests :** La suite de tests locale est 100% stable. Les 1054 tests passent sans échec, et aucune instabilité (flakiness) n'a été détectée sur 10 exécutions consécutives.
2.  **Couverture du Cœur Applicatif :** La logique métier critique est très bien couverte. `plan.py` est à 100%, `analysis_pipeline.py` à 99%, et `scheduler.py` à 100%. Le risque de régression sur ces composants est très faible.
3.  **Fiabilisation des Utilitaires Critiques :** Des modules à haut risque ont été significativement renforcés :
    - `firestore_client.py` (I/O base de données) : couverture passée de 80% à **90%**.
    - `logging_io.py` (écriture des logs CSV/JSON) : couverture passée de 47% à **90%**.
4.  **Robustesse de la Configuration :** Le module `config/env_utils.py` qui gère la configuration et les secrets est couvert à **96%**, garantissant un comportement de démarrage fiable.
5.  **Dette Technique sur les Scripts :** Le répertoire `scripts/` reste une zone à risque. Malgré l'ajout d'une couverture de **88%** au script critique `monitor_roi.py` (parti de 0%), de nombreux autres scripts ne sont pas testés.
6.  **Sécurité des Endpoints :** Les tests existants valident efficacement que les endpoints sensibles (`/schedule`, `/ops/*`, `/tasks/*`) sont bien protégés par authentification.
7.  **Artefacts de Qualité :** Le projet dispose maintenant d'un `TEST_MATRIX.md` pour guider les efforts futurs, d'un `TEST_PLAN.md` pour les validations locales, et d'un script `scripts/smoke_prod.sh` pour les vérifications en production.

### 3. Options Possibles

| Option | Pour | Contre | Effort |
| :--- | :--- | :--- | :--- |
| **1. Go Prod (Risque Acceptable)** | Logique applicative principale sécurisée. Les risques sont connus et isolés. | Un script non-testé pourrait échouer en production et nécessiter une intervention manuelle. | Faible |
| **2. Go Prod Conditionnel (Recommandé)** | Permet la mise en production du service stable tout en gérant le risque des scripts via la documentation et les processus. | Nécessite une discipline opérationnelle pour ne pas utiliser les scripts non validés. | Moyen |
| **3. No-Go Prod (Bloquer et Corriger)** | Sécurité maximale, élimine le risque lié aux scripts. | Effort de test élevé, retarde la mise en production pour des fonctionnalités potentiellement peu utilisées. | Élevé |

### 4. Recommandation Priorisée

**Option 2 : Go Prod Conditionnel.**

Cette approche pragmatique permet de bénéficier de la valeur du service principal, qui est stable et fiable, sans être bloqué par la dette technique des scripts annexes. Le risque est réel mais connu, isolé, et peut être géré par des mesures organisationnelles (documentation, communication) en attendant que la dette soit résorbée.

### 5. Plan d'Action Immédiat

1.  **Créer un guide de sécurité pour les scripts :** Produire un fichier `scripts/README.md` qui liste les scripts "sûrs pour la production" (ex: `monitor_roi.py`) et ceux "à risque" (les autres), avec leurs fonctions.
2.  **Intégrer un check de couverture dans la CI/CD :** Mettre en place un garde-fou (ex: `pytest --cov --cov-fail-under=70`) pour s'assurer qu'aucun nouveau code ne soit fusionné sans un minimum de tests.
3.  **Planifier la suite du renforcement :** Organiser une session de planification pour prioriser l'ajout de tests sur les 2 ou 3 scripts les plus critiques restants.

### 6. Mesures de Contrôle (KPIs Atteints)

- **Pass Rate Local :** **100%**
- **Couverture `firestore_client.py` :** 80% -> **90%**
- **Couverture `logging_io.py` :** 47% -> **90%**
- **Couverture `scripts/monitor_roi.py` :** 0% -> **88%**
- **Tests Flaky (sur 10 runs) :** **0**

### 7. Risques et Limites

1.  **Risque Élevé : Exécution d'un script non testé.**
    - *Description :* Un script critique (ex: `update_excel_with_results.py`) est lancé manuellement et échoue, causant une corruption de données.
    - *Mitigation :* Documentation `scripts/README.md`, communication claire aux équipes opérationnelles.
2.  **Risque Moyen : Changement de structure d'un site de scraping.**
    - *Description :* Le site `boturfers.fr` modifie son HTML, ce qui casse le scraping du plan de courses.
    - *Mitigation :* Le script `smoke_prod.sh` offre une détection de base. Mettre en place un monitoring externe ("canary") serait une amélioration.
3.  **Risque Faible : Erreur de configuration non bloquante.**
    - *Description :* Une variable d'environnement secondaire est mal configurée, mais l'application utilise une valeur par défaut sans planter, masquant le problème.
    - *Mitigation :* Tests robustes sur `env_utils.py` et utilisation de l'endpoint `/debug/config` (si disponible) pour vérifier l'état en production.

### 8. Exemple Concret d'Utilisation

Le script `scripts/smoke_prod.sh` illustre parfaitement la validation de la sécurité et de la configuration :

- **Test sans authentification :**
  ```bash
  # Retourne un code HTTP 403, ce qui est attendu et vérifié
  curl -s -o /dev/null -w "%{http_code}" -X POST https://votre-app.run.app/schedule
  ```
- **Test avec authentification sécurisée :**
  ```bash
  # La clé est lue depuis une variable d'environnement, jamais en clair dans le script
  export HIPPIQUE_INTERNAL_API_KEY="votre_cle"
  ./scripts/smoke_prod.sh https://votre-app.run.app
  ```

### 9. Score de Confiance pour la Mise en Production

**85 / 100**

- **Facteurs Positifs (+85) :** Cœur de l'application très robuste et testé ; endpoints critiques sécurisés et validés ; modules I/O fiabilisés ; aucun test instable.
- **Facteurs Négatifs (-15) :** La dette technique significative sur les scripts représente un risque opérationnel qui doit être activement géré pour éviter des erreurs manuelles en production.

### 10. Questions de Suivi

1.  Quel est le processus d'exécution des scripts du répertoire `scripts/` ? Sont-ils déclenchés manuellement ou via des jobs automatisés, et à quelle fréquence ?
2.  Existe-t-il une volonté et un budget pour adresser la dette de test sur les scripts restants dans les prochains sprints, comme suggéré dans le plan d'action ?
