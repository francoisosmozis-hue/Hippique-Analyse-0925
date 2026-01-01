# Plan de Test - Hippique Orchestrator

Ce document décrit les commandes et procédures pour valider la qualité et la non-régression du projet.

## 1. Validation Locale (Harnais de Test `pytest`)

L'ensemble des tests unitaires et d'intégration sont exécutés avec `pytest`. En raison d'une instabilité détectée avec l'exécuteur parallèle `pytest-xdist`, **toutes les commandes de test doivent être exécutées en mode séquentiel** en utilisant l'option `-n 0`.

### a. Exécution Rapide

Pour une vérification rapide de la non-régression.

```bash
pytest -q -n 0
```
**Résultat Attendu :** Tous les tests doivent passer.

### b. Exécution avec Couverture de Code

Pour générer le rapport de couverture et identifier les zones non testées.

```bash
pytest -n 0 --cov=hippique_orchestrator --cov=config --cov-report=term-missing
```
**Résultat Attendu :** Tous les tests passent et un rapport de couverture s'affiche dans le terminal, indiquant le pourcentage de couverture pour chaque module.

### c. Validation Anti-Flaky (Stabilité)

Pour garantir que les tests sont déterministes, cette commande les exécute 10 fois de suite. Tout échec interrompt le processus.

```bash
for i in $(seq 1 10); do
  echo "--- Passe de test anti-flaky : $i/10 ---"
  pytest -q -n 0
  if [ $? -ne 0 ]; then
    echo "ERREUR : La suite de tests a échoué à la passe $i. Test non déterministe détecté."
    exit 1
  fi
done

echo "SUCCÈS : Les 10 passes de test ont réussi. Aucun test flaky détecté."
```
**Résultat Attendu :** Le script se termine avec le message de succès.

## 2. Validation de Production (Smoke Test)

Un script de "smoke test" est fourni pour valider les fonctionnalités de base d'un environnement déployé (Staging, Production). Il ne valide pas la logique métier mais la disponibilité et la sécurité des endpoints critiques.

### Prérequis

1.  L'URL de base de l'environnement doit être connue (ex: `https://mon-app.run.app`).
2.  Si l'endpoint `/schedule` est sécurisé, la clé API doit être exportée dans une variable d'environnement :
    ```bash
    export HIPPIQUE_INTERNAL_API_KEY="votre-cle-api-secrete"
    ```

### Commande d'Exécution

Le script se trouve dans `scripts/smoke_prod.sh`.

```bash
./scripts/smoke_prod.sh https://votre-url-de-production.com
```

### Scénarios de Test du Smoke Script

Le script exécute les vérifications suivantes :
1.  **Endpoint UI (`/pronostics`) :** Vérifie que la page principale retourne un code HTTP 200.
2.  **Endpoint API (`/api/pronostics`) :** Vérifie que l'API de données retourne un code HTTP 200.
3.  **Endpoint Sécurisé (`/schedule` - Sans Clé) :** Vérifie que l'accès sans clé API est bien rejeté (code HTTP 401 ou 403 attendu).
4.  **Endpoint Sécurisé (`/schedule` - Avec Clé) :** Si la variable `HIPPIQUE_INTERNAL_API_KEY` est définie, vérifie que l'accès avec la clé est autorisé (code HTTP 200 attendu). La clé elle-même n'est jamais affichée.