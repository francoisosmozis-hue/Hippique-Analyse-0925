# Stratégie de Validation et de Test

Ce document décrit la stratégie de test en deux volets du projet, conçue pour garantir la robustesse de la logique métier (offline) et la résilience face aux changements du monde réel (live).

## 1. Tests Offline (pour la CI)

Ces tests constituent la base de notre intégration continue. Ils sont rapides, déterministes et s'exécutent **sans aucune connexion réseau**.

- **Objectif** : Valider la correction de la logique de parsing, la stabilité des IDs, le calcul du drift, et le comportement du Quality Gate.
- **Mécanisme** : Nous utilisons un `FileBasedProvider` qui simule un scraper en lisant des fichiers HTML locaux (`tests/fixtures/html/`). Les résultats du parsing sont validés contre des "golden files" JSON (`tests/fixtures/json_expected/`), qui représentent la sortie attendue parfaite.
- **Exécution** : Ces tests sont automatiquement lancés par `pytest` à chaque commit.

```bash
# Lancer tous les tests offline
pytest
```

## 2. Smoke Test Live (Manuel / Pré-production)

Ce test a pour but de vérifier l'intégration de bout en bout avec les systèmes externes réels. Il est conçu pour être lancé manuellement et est **explicitement bloqué en environnement de CI**.

- **Objectif** : Détecter les ruptures de contrat avec les sites sources (ex: changement de structure HTML) et vérifier que le système est résilient (s'abstient correctement si les données sont invalides plutôt que de planter).
- **Mécanisme** : Le script `scripts/smoke_live.py` utilise un provider réel (`BoturfersProvider`, etc.) pour analyser les 3 premières courses du jour. Il vérifie des invariants de base.
- **Exécution** : L'exécution est protégée par une variable d'environnement `LIVE=1`.

```bash
# Lancer le smoke test avec le provider réel (quand il sera implémenté)
LIVE=1 PROVIDER=boturfers ./scripts/smoke_live.py

# Lancer un "dry-run" du smoke test avec le provider de test
LIVE=1 PROVIDER=file ./scripts/smoke_live.py

# Spécifier une date
LIVE=1 PROVIDER=file DATE=2025-01-20 ./scripts/smoke_live.py
```
