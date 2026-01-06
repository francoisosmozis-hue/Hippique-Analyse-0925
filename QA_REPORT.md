# Rapport Final d'Assurance Qualité - Hippique Orchestrator

**Date :** 2026-01-05
**Version Auditée :** `main`
**Expert QA/DevOps :** Gemini

---

### 1. Constat Synthétique

Le cœur de l'application (`hippique_orchestrator/`) est robuste, bien testé (>95% de couverture sur les modules critiques) et stable (0 test flaky sur 10 runs). Le projet est **conditionnellement prêt pour la production**, à condition de traiter ou d'accepter le risque élevé posé par les scripts annexes du répertoire `scripts/`, qui manquent sévèrement de couverture.

### 2. Analyse

1.  **Stabilité de la suite de tests :** La suite de tests existante est déterministe. Les 1110 tests ont réussi 10 fois consécutivement sans aucun échec, confirmant l'absence de tests "flaky".
2.  **Excellente couverture du cœur applicatif :** Les objectifs de couverture ont été largement dépassés sur les modules critiques identifiés : `plan.py` (100%), `firestore_client.py` (100% après ajout d'un test), `analysis_pipeline.py` (99%). La logique métier principale est fiable.
3.  **Gestion de la configuration robuste :** Le module `config/env_utils.py` est couvert à 97% et son comportement "fail-fast" en production en cas de variable manquante est validé.
4.  **Sécurité des endpoints :** Les endpoints sensibles (`/schedule`, `/ops/*`, `/tasks/*`) sont correctement protégés par des mécanismes d'authentification (clé API et/ou token OIDC), comme validé par les tests de sécurité.
5.  **RISQUE MAJEUR - Scripts non testés :** Une part significative de la logique métier est encapsulée dans le répertoire `scripts/`, dont la plupart des fichiers ont une couverture de 0%. Des fichiers comme `fetch_je_stats.py` (0%) ou `online_fetch_zeturf.py` (60%) contiennent des centaines de lignes de code non validées, présentant un risque opérationnel élevé.
6.  **RISQUE MOYEN - Fragilité des Scrapers :** Bien que les scrapers soient bien testés contre des fixtures statiques, ils manquent de tests de "contrat" pour détecter les changements de structure des sites web cibles. Un test de ce type a été ajouté pour `boturfers` à titre d'exemple, mais le modèle doit être généralisé.
7.  **Tests d'intégration suffisants :** Les tests existants pour l'API `/api/pronostics` et l'UI `/pronostics` valident déjà correctement la stabilité du schéma JSON et l'intégration frontend-backend, conformément aux exigences de la Tâche 4.

### 3. Options Possibles

| Option | Pour | Contre | Effort |
| :--- | :--- | :--- | :--- |
| **1. Lancer en production maintenant** | - Rapidité de déploiement.<br>- Le cœur de l'application est stable. | - Risque élevé de bugs imprévus dans les scripts non testés.<br>- Pas de détection de régression sur ces scripts. | Faible |
| **2. Prioriser la couverture des scripts critiques (Recommandé)** | - Réduit 80% du risque en se concentrant sur 20% des efforts.<br>- Sécurise les workflows les plus importants.<br>- Maintient un bon rythme de déploiement. | - Les scripts moins critiques restent une zone d'ombre.<br>- Effort de refactoring/test non nul. | Moyen |
| **3. Viser 90% de couverture globale** | - Robustesse maximale.<br>- Quasiment aucun risque de régression. | - Effort très élevé, potentiellement plusieurs semaines.<br>- Retarde significativement la mise en production. | Élevé |

### 4. Recommandation Priorisée

**Option 2 : Prioriser la couverture des scripts critiques.**

Cette approche offre le meilleur ratio bénéfice/risque. Elle permet de sécuriser les fonctionnalités essentielles qui tournent en production (via cron ou autres triggers) tout en acceptant un risque maîtrisé pour les scripts utilitaires moins fréquents. Cela permet une mise en production rapide mais sécurisée.

### 5. Plan d’Action Immédiat

1.  **Intégrer les patchs de tests actuels :** Appliquer le `git diff` de cette session, qui ajoute les tests pour `firestore_client`, la sécurité de `/schedule` et la robustesse du scraper `boturfers`.
2.  **Augmenter la couverture des 2 scripts les plus risqués :** Isoler la logique pure des scripts `scripts/online_fetch_zeturf.py` et `scripts/fetch_je_stats.py` dans des fonctions testables et viser une couverture de **>80%** sur ces nouvelles fonctions.
3.  **Finaliser le protocole "Canary" :** Appliquer le test de non-régression structurelle (ajouté à `test_scraper_boturfers_robustness.py`) à tous les autres scrapers critiques (`geny`, `zoneturf_client`).

### 6. Mesures de Contrôle (KPIs)

- **Couverture `plan.py` :** Maintenir à 100%.
- **Couverture `firestore_client.py` :** Maintenir à 100%.
- **Couverture `analysis_pipeline.py` :** Maintenir >99%.
- **Couverture `config/env_utils.py` :** Maintenir >97%.
- **Couverture des fonctions critiques extraites des `scripts` :** Atteindre >80%.
- **Taux de succès des tests :** Maintenir à 100% sur 10+ runs consécutifs.

### 7. Risques et Limites

1.  **Rupture des Scrapers (Élevé) :** Un site externe change sa structure HTML. **Mitigation :** Généralisation des tests de contrat structurel et documentation du protocole "canary" (cf. `TEST_PLAN.md`).
2.  **Bug dans un script non priorisé (Moyen) :** Un script jugé non-critique contient un bug qui affecte une opération manuelle. **Mitigation :** Communication claire à l'équipe sur les zones non couvertes et les risques associés.
3.  **Dérive de performance (Faible) :** Le temps de traitement d'une tâche augmente silencieusement. **Mitigation :** Mettre en place un monitoring externe sur la durée d'exécution des Cloud Functions/Run.

### 8. Exemple Concret d'Utilisation

Le script `scripts/smoke_prod.sh` permet une validation rapide post-déploiement.

**Cas d'usage :**
```bash
# 1. Exporter l'URL de l'application et la clé API
export APP_URL="https://mon-app-en-prod.a.run.app"
export HIPPIQUE_INTERNAL_API_KEY="ma-super-cle-secrete"

# 2. Lancer le script
bash scripts/smoke_prod.sh

# 3. Analyser la sortie
# Le script doit afficher [OK] pour tous les tests, y compris :
# 🧪 Running test: /schedule requires auth (403)                [OK]
# 🧪 Running test: /schedule with API key works (200)             [OK]
# Si la clé est incorrecte ou manquante, le second test échouera ou sera sauté,
# validant ainsi la chaîne de sécurité de bout en bout.
```

### 9. Score de Confiance

**75/100**

Le score est solide grâce à la robustesse du cœur de l'application et à la stabilité de la suite de tests. Il n'atteint pas 90+ uniquement à cause de la dette technique et du manque de visibilité sur les `scripts/`. L'exécution du plan d'action recommandé ferait passer ce score à **90/100**.

### 10. Questions de Suivi

1.  Quels scripts du répertoire `scripts/` sont absolument critiques pour les opérations quotidiennes (ex: exécutés par des cron jobs) et lesquels sont des outils de développement ou d'analyse ponctuelle ?
2.  Existe-t-il une volonté à moyen terme de refactoriser la logique des scripts les plus complexes (`online_fetch_zeturf.py`) pour mieux l'intégrer au cœur de l'application, et ainsi la rendre plus testable et maintenable ?
