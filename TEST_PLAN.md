# Plan de Test - hippique-orchestrator

Ce document décrit les procédures pour valider le bon fonctionnement de l'application, que ce soit localement ou en production.

## 1. Validation Locale

La validation locale repose sur la suite de tests `pytest`. Elle doit être exécutée avant toute intégration de code.

### 1.1. Exécution simple et rapide

Pour lancer tous les tests en mode silencieux. Utile pour une vérification rapide.

```bash
python3 -m pytest -q
```
**Résultat attendu :** `OK` et un résumé des tests passés.

### 1.2. Exécution avec rapport de couverture

Pour analyser la couverture de code des modules de l'application.

```bash
python3 -m pytest --cov=hippique_orchestrator
```
**Résultat attendu :** Un tableau détaillé affichant le pourcentage de couverture pour chaque fichier du module `hippique_orchestrator`.

### 1.3. Vérification de la stabilité (Anti-Flaky)

Pour s'assurer qu'aucun test n'est instable, la suite est exécutée 10 fois consécutivement. Le moindre échec interrompt le processus.

```bash
for i in $(seq 1 10); do \
  echo "--- Exécution anti-flaky $i/10 ---"; \
  python3 -m pytest -q || { echo "ERREUR : Un test instable a été détecté à l'exécution $i." >&2; exit 1; }; \
done && echo "Tests stables sur 10 exécutions."
```
**Résultat attendu :** Le message final `Tests stables sur 10 exécutions.` sans aucune interruption.

## 2. Validation en Production (Smoke Test)

Un script de "smoke test" est fourni pour effectuer des vérifications de base sur un environnement de production. Il ne se substitue pas aux tests locaux mais agit comme un gardien de la santé de l'application déployée.

**Emplacement du script :** `scripts/smoke_prod.sh`

### 2.1. Prérequis

Le script nécessite deux variables d'environnement :
- `BASE_URL`: L'URL de base de l'application déployée (ex: `https://hippique-orchestrator-xxxx.run.app`).
- `HIPPIQUE_INTERNAL_API_KEY`: La clé API secrète pour accéder aux endpoints protégés. **Cette clé ne doit jamais être affichée ni stockée dans le code.**

### 2.2. Actions du script

Le script `smoke_prod.sh` effectue les vérifications suivantes :

1.  **Endpoint de santé (`/health`)** : Vérifie que l'application est en ligne et répond `200 OK`.
2.  **Endpoint UI (`/pronostics`)** : Vérifie que l'interface utilisateur se charge correctement (`200 OK`).
3.  **Endpoint API (`/api/pronostics`)** : Vérifie que l'API de pronostics répond correctement (`200 OK`) avec une structure JSON valide.
4.  **Sécurité de l'ordonnancement (`/schedule`)** :
    - Lance un appel **sans** la clé API et s'attend à recevoir une erreur `403 Forbidden`.
    - Lance un appel **avec** la clé `HIPPIQUE_INTERNAL_API_KEY` et s'attend à recevoir une réponse `200 OK`, confirmant que la planification (en `dry_run`) a été déclenchée avec succès.

### 2.3. Exécution

```bash
# S'assurer que le script est exécutable
chmod +x scripts/smoke_prod.sh

# Exporter les variables requises
export BASE_URL="URL_DE_PROD"
export HIPPIQUE_INTERNAL_API_KEY="VOTRE_CLE_API_SECRETE"

# Lancer le script
./scripts/smoke_prod.sh
```
**Résultat attendu :** Une sortie indiquant le succès de chaque étape. Toute erreur entraînera la sortie du script avec un code non nul.
