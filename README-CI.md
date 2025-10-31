# Intégration continue : CI – Python

Ce dépôt inclut un workflow GitHub Actions nommé **CI – Python**.

## Comment déclencher la CI
- **Automatique** : sur chaque `push` vers `main`, `develop`, ou une branche commençant par `feat/` ou `fix/`, ainsi que sur chaque `pull_request`.
- **Manuel** : onglet **Actions** → workflow **CI – Python** → bouton **Run workflow**.

## Résultats et rapports
- Onglet **Checks** de la PR :
  - Résumé des jobs (lint, tests, smoke).
  - Rapport JUnit publié via **Test Reporter** pour consulter les tests en échec/réussite.
- **Artefacts téléchargeables** : `reports/pytest.xml`, `reports/coverage.xml`, `.coverage` et éventuels journaux de smoke test.

## Rendre la CI bloquante
1. Ouvrir **Settings → Branches**.
2. Ajouter ou modifier une **branch protection rule** sur la branche souhaitée (ex. `main`).
3. Cocher **Require status checks to pass before merging** et sélectionner **CI – Python**.

## Activer le smoke test
Le job `smoke` s’exécute automatiquement si `data/ci_sample/` contient des données de démonstration **et** que `pipeline_run.py` est présent à la racine.

Préparation suggérée :
1. Créer le dossier `data/ci_sample/` et y ajouter un échantillon minimal de données nécessaires au pipeline.
2. Vérifier que `pipeline_run.py` accepte les options `--dry-run`, `--no-upload`, `--data-dir`.
3. Commiter ces fichiers pour activer le job lors de la CI.

Si `pipeline_run.py` est absent, le job indique que le smoke test est ignoré.
