# Plan de Test

Ce document détaille les procédures pour valider le bon fonctionnement de l'application, localement et en production.

## 1. Validation Locale

Ces commandes doivent être exécutées avant toute intégration de code.

### 1.1. Tests Unitaires et de Couverture

Assure la non-régression, la stabilité et une couverture de code minimale.

```bash
# Lance tous les tests en parallèle, génère un rapport de couverture
pytest -n auto --cov=hippique_orchestrator --cov-report term-missing --cov-fail-under=70
```

*   **Critère d'acceptation :** Tous les tests doivent passer (`100% passed`) et la couverture ne doit pas être inférieure à 70%.

### 1.2. Validation du Linting et du Style

Garantit la conformité du code aux standards du projet.

```bash
# Lance le linter ruff
ruff check .
```

*   **Critère d'acceptation :** Aucune erreur rapportée par `ruff`.

## 2. Validation en Production (Post-Déploiement)

Ces vérifications doivent être effectuées après chaque déploiement sur l'environnement de production.

### 2.1. Test de Santé de l'API

Vérifie que le service est en ligne et répond correctement.

```bash
# Interroge l'endpoint des pronostics pour la date du jour
curl -s "https://hippique-orchestrator-1084663881709.europe-west1.run.app/api/pronostics?date=$(date +%F)" | jq .
```

*   **Critère d'acceptation :** Le JSON retourné doit contenir une clé `courses` avec une liste non-vide, sans erreurs manifestes.

### 2.2. Test de Santé de l'Interface Utilisateur

Valide que l'interface se charge et affiche les données.

1.  Ouvrir un navigateur web.
2.  Accéder à l'URL : `https://hippique-orchestrator-1084663881709.europe-west1.run.app/pronostics`
3.  Vérifier visuellement que la grille des courses s'affiche et contient des informations.
4.  Ouvrir la console de développement pour vérifier l'absence d'erreurs JavaScript.

*   **Critère d'acceptation :** La page se charge, les données sont présentes et aucune erreur n'est visible en console.

### 2.3. Surveillance de la Création des Tâches

Confirme que le scheduler fonctionne comme attendu.

1.  Accéder à la console Google Cloud.
2.  Naviguer vers "Cloud Tasks".
3.  Vérifier que les tâches pour les analyses `H-5` et `H-30` ont été créées aux heures prévues.

*   **Critère d'acceptation :** Les tâches sont présentes dans la file d'attente avec les bons paramètres.