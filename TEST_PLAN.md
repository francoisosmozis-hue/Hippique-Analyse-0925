# Plan de Tests Hippique Orchestrator

Ce document décrit les procédures de test locales et de validation en environnement de production (smoke tests) pour le projet Hippique Orchestrator.

## Commandes de Tests Locaux

Pour exécuter la suite complète de tests locaux, y compris la génération de rapport de couverture et la vérification de l'absence de tests instables (flaky tests) :

1.  **Exécuter tous les tests (mode silencieux) :**
    ```bash
    pytest -q
    ```
    *Résultat attendu :* Tous les tests doivent passer (`xxx passed`).

2.  **Exécuter les tests avec rapport de couverture détaillé :**
    ```bash
    pytest --cov=hippique_orchestrator --cov-report=term-missing
    ```
    *Résultat attendu :* Un rapport de couverture affichant les pourcentages de couverture par module, incluant les lignes manquantes.

3.  **Vérification anti-flaky (10 exécutions consécutives) :**
    ```bash
    for i in $(seq 1 10); do echo "--- Anti-flaky run $i/10 ---"; pytest -q || (echo "FAILURE: Flaky test detected on run $i" && exit 1); done && echo "SUCCESS: No flaky tests detected in 10 runs."
    ```
    *Résultat attendu :* Le message "SUCCESS: No flaky tests detected in 10 runs." s'affiche, confirmant la stabilité de la suite de tests.

## Scripts de Smoke Test en Production

Ce script est destiné à être exécuté en environnement de production (ex: Cloud Run) pour valider le bon fonctionnement des endpoints critiques.

**Prérequis :** L'URL de base du service doit être fournie par l'utilisateur (par exemple, via la variable d'environnement `SERVICE_URL`). Pour les tests d'authentification, la clé `HIPPIQUE_INTERNAL_API_KEY` doit être définie.

### Commande d'exécution du Smoke Test

```bash
scripts/smoke_prod.sh <SERVICE_URL>
```

### Détail du Script `scripts/smoke_prod.sh` (à créer)

Le script effectuera les vérifications suivantes :

1.  **`GET /pronostics` (UI Frontend) :** Vérifie que la page HTML principale se charge et contient des marqueurs spécifiques.
    *   *Attendu :* Statut HTTP 200, contenu HTML.
2.  **`GET /api/pronostics` (API principale) :** Vérifie que l'API retourne une réponse JSON valide.
    *   *Attendu :* Statut HTTP 200, JSON non vide.
3.  **`POST /schedule` sans clé API :** Vérifie que l'endpoint protégé renvoie une erreur 403.
    *   *Attendu :* Statut HTTP 403.
4.  **`POST /schedule` avec clé API valide :** Vérifie que l'endpoint protégé fonctionne avec une clé valide (simule un appel de Cloud Tasks).
    *   *Attendu :* Statut HTTP 200.

**NOTE :** Les clés API sensibles ne doivent jamais être affichées dans les logs ou le script lui-même. La clé sera lue depuis la variable d'environnement `HIPPIQUE_INTERNAL_API_KEY`.
