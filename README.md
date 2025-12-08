# Analyse Hippique – GPI v5.1 (Budget 5€ / EV+)

Pipeline **pro** pour planifier, capturer H‑30 / H‑5, analyser et consigner chaque course (tickets, EV/ROI, pastille verte/rouge) avec export Google Cloud Storage + mise à jour Excel.

---

## 🔎 Vue d’ensemble

Ce projet est un service Cloud Run qui orchestre l'analyse des courses hippiques françaises.

- **09:00 Paris** : Un job Cloud Scheduler appelle l'endpoint `/schedule` pour générer le **planning du jour** (réunions, courses, horaires, URLs).
- **H-30 / H-5** : Pour chaque course, des tâches sont créées dans Cloud Tasks. Ces tâches appellent l'endpoint `/tasks/run-phase` qui orchestre la capture des cotes et l'analyse GPI.
- **Post‑results** : Un autre processus (non couvert par ce service) peut récupérer les arrivées officielles pour mettre à jour les suivis.

**Endpoints principaux :**
- `GET /pronostics/ui`: Affiche la page web des pronostics.
- `GET /pronostics`: API JSON qui fournit les tickets générés pour une date donnée.
- `POST /schedule`: Déclenche la planification pour une date donnée.
- `POST /tasks/run-phase`: Endpoint interne appelé par Cloud Tasks pour analyser une course.

**Standards verrouillés** (GPI v5.1 / v5.2) :
- Budget **max 5 €** / course et **2 tickets max** : un seul SP + un combiné (CP/CG/Trio/ZE4) si et seulement si **EV ≥ +40 %** et **payout attendu ≥ 10 €**.
- SP « Kelly fractionné » : **ROI_SP ≥ +20 %**, **≤ 60 % du budget** engagé sur un même cheval.
- Combinés calibrés : fichier `config/payout_calibration.yaml` valide obligatoire.
- Surcote place : **overround place > 1.30 ⇒ combinés bloqués**.
- La configuration détaillée se trouve dans `hippique_orchestrator/config/gpi_v52.yml`.

---

## ⚙️ Installation locale

1) **Python 3.12+**
2) Dépendances :
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```
3) Variables locales : dupliquez `.env.example` en `.env` et ajustez si besoin.

---

## ✅ Tests

La CI exécute les tests unitaires via `pytest -m unit`. Pour lancer tous les tests :

```bash
pytest
```

---

## 🧰 Architecture & Déploiement

- Le service est une application **FastAPI** définie dans `hippique_orchestrator/service.py`.
- L'analyse est orchestrée dans `hippique_orchestrator/analysis_pipeline.py` qui appelle la logique de génération de tickets dans `hippique_orchestrator/pipeline_run.py`.
- La persistance est gérée par `hippique_orchestrator/storage.py` (GCS) et `hippique_orchestrator/firestore_client.py` (Firestore).
- Le déploiement est automatisé via `cloudbuild.yaml` qui build une image Docker (`Dockerfile`) et la déploie sur Cloud Run.