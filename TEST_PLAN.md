# Plan de Test - Hippique Orchestrator

Ce document centralise les commandes et procédures pour valider l'application à différentes étapes du cycle de vie (développement, CI, production).

## 1. Validation Locale Complète

Ces commandes doivent être exécutées depuis la racine du projet.

### 1.1. Exécution de la suite de tests complète

Lance l'intégralité des tests unitaires et d'intégration avec un rapport de couverture.

**Commande :**
```bash
pytest --cov=hippique_orchestrator --cov=config
```

**Résultat Attendu :**
- `100% passed`
- Aucun échec ou erreur.
- Un rapport de couverture (`coverage report`) s'affiche dans le terminal.

### 1.2. Vérification de non-régression (Anti-Flaky)

Exécute la suite de tests 10 fois consécutivement pour détecter toute instabilité (tests "flaky").

**Commande :**
```bash
for i in $(seq 1 10); do \
  echo "\n--- Validation Run $i/10 ---\n"; \
  pytest -q; \
  if [ $? -ne 0 ]; then \
    echo "\nERREUR : Un test flaky a été détecté lors du run $i. Arrêt."; \
    exit 1; \
  fi; \
done && echo "\nSUCCÈS : Tous les tests ont passé 10/10 runs."
```

**Résultat Attendu :**
- Le script se termine avec le message : `SUCCÈS : Tous les tests ont passé 10/10 runs.`

## 2. Smoke Tests en Production

Ces tests sont conçus pour être lancés sur un environnement déployé (production ou pre-production). Ils ne dépendent que de `curl` et `jq`.

### 2.1. Prérequis

1.  **URL de l'application :** La variable d'environnement `APP_URL` doit être définie.
    ```bash
    export APP_URL="https://hippique-orchestrator-xxxxxxxx-ew.a.run.app"
    ```
2.  **Clé API (si nécessaire) :** Pour les endpoints sécurisés, la variable d'environnement `HIPPIQUE_INTERNAL_API_KEY` doit être définie.
    ```bash
    export HIPPIQUE_INTERNAL_API_KEY="votre-cle-secrete"
    ```

### 2.2. Script de Smoke Test

Le script `scripts/smoke_prod.sh` exécute les vérifications essentielles.

**Commande :**
```bash
bash scripts/smoke_prod.sh
```

**Résultat Attendu :**
- Le script affiche `OK` pour chaque test réussi.
- Le script se termine avec le message `Smoke tests passed successfully.` et un code de sortie 0.

## 3. Protocole "Canary" pour les Scrapers

Pour détecter les changements de structure des sites web scrapés, une validation manuelle ou semi-automatisée peut être effectuée.

**Procédure :**

1.  **Identifier les fixtures :** Les fichiers HTML de référence sont dans `tests/fixtures/`.
2.  **Lancer les tests de robustesse :** Ces tests agissent comme des "canary tests" contre les fixtures.
    ```bash
    pytest tests/test_scraper_boturfers_robustness.py
    ```
3.  **En cas d'échec d'un scraper en production :**
    a. Télécharger la nouvelle page HTML du site (ex: `wget -O new_programme.html <URL>`).
    b. Remplacer la fixture correspondante par ce nouveau fichier.
    c. Relancer le test de robustesse (`test_programme_fixture_has_expected_structure`).
    d. Le test échouera en indiquant précisément le sélecteur CSS qui a changé, guidant ainsi la mise à jour du scraper.
