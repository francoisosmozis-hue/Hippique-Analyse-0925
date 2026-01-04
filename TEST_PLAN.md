# Plan de Test - Hippique Orchestrator

Ce document centralise les commandes de validation qualité à exécuter localement pour garantir la non-régression et la stabilité du projet.

## 1. Validation Rapide

À utiliser durant le développement pour une vérification rapide des tests impactés.

```bash
pytest -q
```
- **Résultat Attendu** : `... passed in ...s`. Aucun test en échec (`failed`) ou en erreur (`error`).

## 2. Validation Complète avec Couverture

À lancer avant de commiter ou de proposer une merge request. Permet de vérifier l'ensemble de la suite de tests et de mesurer l'impact des changements sur la couverture de code.

```bash
pytest --cov=hippique_orchestrator --cov=config --cov-report term-missing
```
- **Résultat Attendu** :
    - Aucun test en échec.
    - Un rapport de couverture s'affiche, listant le pourcentage de couverture pour chaque fichier. Les nouveaux modules doivent atteindre les objectifs définis dans la `TEST_MATRIX.md`.

## 3. Détection de Tests Instables (Flaky Tests)

À exécuter en cas de doute sur la stabilité des tests ou avant une release majeure. Cette commande lance la suite de tests 10 fois de suite et s'arrête à la première erreur.

```bash
for i in $(seq 1 10); do 
    echo "--- Exécution Anti-Flaky : $i/10 ---"
    if ! pytest -q; then 
        echo "ERREUR : Test instable (flaky) détecté à l'exécution $i !"
        exit 1
    fi
done && echo "SUCCÈS : Aucun test instable détecté sur 10 exécutions."
```
- **Résultat Attendu** : Le message final `SUCCÈS : Aucun test instable détecté sur 10 exécutions.`

---

*Ce plan de test doit être maintenu à jour à mesure que de nouvelles procédures de validation sont ajoutées.*
