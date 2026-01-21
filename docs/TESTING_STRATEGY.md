# Stratégie de Test du Projet

Ce projet utilise une stratégie de test à deux niveaux pour garantir à la fois la robustesse de la logique métier et la résilience de la collecte de données en conditions réelles.

## 1. Tests Offline (CI/CD)

Ces tests sont au cœur de notre pipeline d'intégration continue. Ils sont conçus pour être **100% offline**, rapides et déterministes.

- **Objectif** : Valider la logique de parsing, la stabilité des identifiants, la correction des calculs (ex: qualité des données) et la conformité aux contrats de données (Pydantic).
- **Principe** : Nous utilisons un `FileBasedProvider`, une implémentation de notre interface `ProgrammeProvider` qui lit des fichiers HTML locaux (`tests/fixtures/html/`) au lieu de faire des requêtes HTTP. Les résultats du parsing sont comparés à des "golden files" JSON (`tests/fixtures/json_expected/`) qui représentent la sortie attendue.
- **Exécution** : Ces tests s'exécutent avec une simple commande `pytest`. Ils sont automatiquement découverts et lancés par notre CI à chaque commit.

```bash
# Exécuter tous les tests offline
pytest

# Ou via le Makefile
make test
```

## 2. Smoke Test Live (Pré-production / Manuel)

Ce test est conçu pour être lancé manuellement ou dans un environnement de pré-production. Il a pour but de vérifier que la chaîne de collecte et d'analyse fonctionne de bout en bout avec un **provider réel** sur des **données live**.

- **Objectif** : Détecter les ruptures de contrat avec les sites web sources (ex: changement de structure HTML), valider la connectivité, et s'assurer que le système est résilient (par exemple, qu'il s'abstient correctement si les données sont incomplètes).
- **Principe** : Le script `scripts/smoke_live.py` utilise un *vrai* `ProgrammeProvider` (ex: `BoturfersProvider`) pour récupérer les 3 premières courses du jour. Il vérifie des invariants de base (ex: des courses sont trouvées, les `race_uid` sont générés) et la logique d'abstention.
- **Guardrails** :
    - Ce script **ne s'exécute pas** si la variable d'environnement `LIVE=1` n'est pas explicitement définie.
    - Il **se désactive automatiquement** si une variable d'environnement `CI` est détectée.
- **Exécution** :

```bash
# Lancer le smoke test avec le provider par défaut (Boturfers)
LIVE=1 ./scripts/smoke_live.py

# Tester avec le provider de fichier pour un "dry-run"
LIVE=1 PROVIDER=file ./scripts/smoke_live.py

# Spécifier une date
LIVE=1 DATE=2025-12-25 ./scripts/smoke_live.py
```
