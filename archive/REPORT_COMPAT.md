# RAPPORT D'AUDIT ET DE COMPATIBILITÉ - GPI v5.1

Date : 11/11/2025
Scope : `~/francoisosmozis`
Projet cible : `~/francoisosmozis/hippique-orchestrator`

## 1. Inventaire des projets détectés

- `/hippique-orchestrator` (Projet principal)
- `/zeturf-scraper-v2` (Bibliothèque de scraping spécialisée)
- `/pmu-api-client` (Client API pour PMU)
- `/ev-simulation-notebooks` (Notebooks Jupyter d'analyse et de simulation)
- `/gpi-deployment-tools` (Scripts de déploiement Cloud Run & GKE)
- `/old-zeturf-parser-v1` (Ancienne version, archivée)

## 2. Tableau de compatibilité et de décision

| Projet                      | Type          | Réutilisable tel quel ? | Adaptations nécessaires                                                              | Impact attendu | Décision   |
| --------------------------- | ------------- | ----------------------- | ------------------------------------------------------------------------------------ | -------------- | ---------- |
| `hippique-orchestrator`     | **Projet**    | N/A                     | Projet cible de la consolidation.                                                    | **N/A**        | **CIBLE**  |
| `zeturf-scraper-v2`         | Outils        | Oui                     | Intégrer le parseur principal pour remplacer/renforcer `online_fetch_zeturf.py`.     | **Élevé**      | **Intégrer** |
| `pmu-api-client`            | Outils        | Non                     | Le client est spécifique à une API non utilisée. Logique de parsing non compatible.    | Faible         | Ignorer    |
| `ev-simulation-notebooks`   | Données/Analyse | Partiellement           | Extraire les fonctions de calcul de variance et de RoR (Risk of Ruin) des notebooks. | Moyen          | **Intégrer** |
| `gpi-deployment-tools`      | Outils (CI/CD)  | Oui                     | Copier les scripts `cloudbuild.yaml` et `deploy.sh` dans un dossier `ci/`.           | **Élevé**      | **Intégrer** |
| `old-zeturf-parser-v1`      | Outils        | Non                     | Obsolète et remplacé par `zeturf-scraper-v2`.                                        | Nul            | **Archiver** |

## 3. Propositions concrètes

### Intégration

1.  **`zeturf-scraper-v2`**
    *   **Action** : Copier le contenu de `zeturf-scraper-v2/src/parser.py` dans `hippique-orchestrator/src/scrapers/boturfers_parser.py` pour consolider la logique de scraping la plus récente.
    *   **Raison** : Centraliser le code de scraping le plus performant et supprimer les anciennes versions.
2.  **`ev-simulation-notebooks`**
    *   **Action** : Transposer les fonctions de calcul de `kelly.ipynb` et `risk_of_ruin.ipynb` dans un nouveau fichier `hippique-orchestrator/src/kelly.py`.
    *   **Raison** : Industrialiser les fonctions de simulation pour les rendre appelables par le `pipeline_run.py`.
3.  **`gpi-deployment-tools`**
    *   **Action** : Créer un dossier `hippique-orchestrator/ci/` et y copier `gpi-deployment-tools/cloudbuild.yaml` et `gpi-deployment-tools/deploy.sh`.
    *   **Raison** : Doter le projet de scripts de déploiement standardisés et prêts à l'emploi.

### Archivage

1.  **`old-zeturf-parser-v1`**
    *   **Action** : Compresser le dossier en `old-zeturf-parser-v1.tar.gz` et le déplacer dans un dossier `~/archives/`.
    *   **Raison** : Libérer de l'espace et éviter toute confusion avec du code obsolète.

### Ignorés

1.  **`pmu-api-client`** : La logique n'est pas pertinente pour le scraping ZEturf/Boturfers.

## 4. Plan de patch (non destructif)

L'intégration se fera par des copies ciblées pour ne pas altérer les projets sources durant cette phase.

```bash
# Création de la structure cible dans hippique-orchestrator
mkdir -p ~/francoisosmozis/hippique-orchestrator/src/scrapers
mkdir -p ~/francoisosmozis/hippique-orchestrator/ci
mkdir -p ~/francoisosmozis/archives

# 1. Intégration du scraper
cp ~/francoisosmozis/zeturf-scraper-v2/src/parser.py ~/francoisosmozis/hippique-orchestrator/src/scrapers/boturfers_parser.py

# 2. Intégration des outils de déploiement
cp ~/francoisosmozis/gpi-deployment-tools/cloudbuild.yaml ~/francoisosmozis/hippique-orchestrator/ci/
cp ~/francoisosmozis/gpi-deployment-tools/deploy.sh ~/francoisosmozis/hippique-orchestrator/ci/

# 3. Archivage de l'ancien parser
tar -czf ~/francoisosmozis/archives/old-zeturf-parser-v1.tar.gz -C ~/francoisosmozis/ old-zeturf-parser-v1
# rm -rf ~/francoisosmozis/old-zeturf-parser-v1 # Commande de suppression à exécuter manuellement après validation

# 4. Création du stub pour les fonctions de simulation (à remplir manuellement depuis les notebooks)
touch ~/francoisosmozis/hippique-orchestrator/src/kelly.py
```
