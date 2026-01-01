# Test Plan - Projet Hippique Orchestrator

Ce document décrit les procédures de validation pour le projet, incluant les tests locaux et les scripts de vérification en production ("smoke tests").

## 1. Validation Locale

La validation locale est la pierre angulaire de l'assurance qualité pour ce projet. Elle doit être exécutée avant tout déploiement.

### 1.1. Installation des dépendances

Assurez-vous que toutes les dépendances de développement sont installées :

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

### 1.2. Exécution de la suite de tests complète

Pour lancer tous les tests unitaires et d'intégration, utilisez la commande suivante. Cela garantit que toutes les fonctionnalités existantes sont intactes.

```bash
pytest -q
```

**Résultat attendu :** Tous les tests doivent passer (`OK`). Aucun échec (`FAILED`) ou erreur (`ERROR`) n'est acceptable.

### 1.3. Génération du rapport de couverture

Pour vérifier que les modules critiques restent bien couverts, générez le rapport de couverture :

```bash
pytest --cov=. --cov-report=term-missing
```

**Résultat attendu :** Le rapport s'affichera dans le terminal. Les modules critiques ciblés doivent maintenir une couverture élevée :
- `hippique_orchestrator/plan.py`: > 80%
- `hippique_orchestrator/firestore_client.py`: > 80%
- `hippique_orchestrator/analysis_pipeline.py`: > 80%
- `hippique_orchestrator/scrapers/boturfers.py`: > 80%
- `hippique_orchestrator/gcs_utils.py`: > 80%

### 1.4. Vérification de la stabilité (Anti-Flaky)

Pour s'assurer qu'aucun test n'est intermittent ("flaky"), exécutez la suite de tests en boucle. Un échec sur l'une des itérations signale une instabilité à corriger.

```bash
for i in $(seq 1 10); do \
  echo "Run $i/10..."; \
  pytest -q --disable-warnings || (echo "Flaky test detected on run $i!" && exit 1); \
done
```

**Résultat attendu :** La boucle doit se terminer avec succès après 10 itérations.

## 2. Validation en Production (Smoke Tests)

Après un déploiement réussi, une série de vérifications rapides doit être effectuée pour s'assurer que le service est opérationnel.

### 2.1. Prérequis

Le script de smoke test requiert deux variables d'environnement :
- `SERVICE_URL`: L'URL de base du service déployé (ex: `https://mon-service-prod.run.app`).
- `HIPPIQUE_INTERNAL_API_KEY`: La clé API requise pour les endpoints sécurisés comme `/schedule`.

**NE JAMAIS HARCODER LA CLÉ DANS LE SCRIPT.**

### 2.2. Exécution du script

```bash
export SERVICE_URL="https://your-service-url.run.app"
export HIPPIQUE_INTERNAL_API_KEY="your-secret-api-key"
bash scripts/smoke_prod.sh
```

**Résultat attendu :** Le script affichera `OK` pour chaque endpoint testé. Toute autre sortie indique un problème en production.
