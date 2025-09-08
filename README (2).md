# Analyse Hippique – GPI v5.1 (Budget 5€ / EV+)

Pipeline **pro** pour planifier, capturer H‑30 / H‑5, analyser et consigner chaque course (tickets, EV/ROI, pastille verte/rouge) avec export Drive + mise à jour Excel.

---

## 🔎 Vue d’ensemble

- **09:00 Paris** : génération du **planning du jour** (réunions, courses, horaires, URLs).
- **Scheduler (*/5 min)** : déclenche auto les fenêtres **H‑30** (snapshots cotes + stats) et **H‑5** (analyse GPI v5.1 + tickets).
- **Post‑results (*/15 min)** : récupération **arrivées officielles**, **mise à jour Excel** (ROI réel), **upload Drive**.

**Standards verrouillés** (GPI v5.1) :  
- Budget **max 5 €** / course, **2 tickets max** (SP + 1 combiné éventuel).  
- **EV globale ≥ +40 %** et **ROI estimé ≥ +20 %** pour valider le **vert**.  
- Combinés uniquement si **payout attendu > 10 €** (calibration).  
- **Kelly fractionné** avec **cap 60 %** par cheval.

---

## 🗂️ Arborescence

```
analyse-hippique/
├─ README.md
├─ requirements.txt
├─ .env.example
├─ config/
│  ├─ gpi_v51.yml
│  ├─ payout_calibration.yaml
│  └─ sources.yml
├─ data/
│  ├─ planning/          # programmes du jour (JSON)
│  ├─ snapshots/         # H-30 / H-5 (cotes + stats)
│  ├─ analyses/          # analyses H-5 (tickets + pastille)
│  └─ results/           # arrivées + exports Excel/CSV
├─ excel/
│  └─ modele_suivi_courses_hippiques.xlsx
├─ scripts/
│  ├─ runner_chain.py
│  ├─ pipeline_run.py
│  ├─ simulate_ev.py
│  ├─ simulate_wrapper.py
│  ├─ validator_ev.py (ou validator_ev_v2.py)
│  ├─ online_fetch_zeturf.py
│  ├─ fetch_je_stats.py
│  ├─ fetch_je_chrono.py
│  ├─ p_finale_export.py
│  ├─ get_arrivee_geny.py
│  ├─ update_excel_with_results.py
│  └─ drive_sync.py
└─ .github/workflows/
   ├─ daily_planning.yml
   ├─ race_scheduler.yml
   └─ post_results.yml
```

---

## ⚙️ Installation locale

1) **Python 3.12+**
2) Dépendances :
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```
**Ex. de packages** : `pandas`, `openpyxl`, `pyyaml`, `requests`, `google-api-python-client`, `google-auth`, `google-auth-httplib2`, `google-auth-oauthlib` …

3) Variables locales : dupliquez `.env.example` en `.env` et ajustez si besoin.

---

## 🔐 Secrets GitHub (obligatoires)

Dans **Settings → Secrets and variables → Actions** du repo, créer :
- `DRIVE_FOLDER_ID` → dossier Drive de destination
- `GOOGLE_CREDENTIALS_JSON` → contenu intégral du `credentials.json` (Service Account)

> ⚠️ **Ne pas** committer `credentials.json` en clair.

---

## 🧰 Workflows GitHub

### 1) `daily_planning.yml` — 09:00 Paris
- Appelle `scripts/online_fetch_zeturf.py --mode planning`  
- Écrit `data/planning/YYYY-MM-DD.json`

### 2) `race_scheduler.yml` — toutes les 5 min
- Appelle `scripts/runner_chain.py` avec fenêtres **H‑30** puis **H‑5**.
- **H‑30** : snapshots cotes + stats (JSON).  
- **H‑5** : enrichissement J/E + chronos (si dispo) → **pipeline** (tickets, EV/ROI) → **pastille** (VERT/ROUGE) → export JSON/CSV → **upload Drive**.

### 3) `post_results.yml` — toutes les 15 min
- `get_arrivee_geny.py` → `data/results/ARRIVEES.json`
- `update_excel_with_results.py` → met à jour `excel/modele_suivi_courses_hippiques.xlsx`
- Upload Excel + résultats sur Drive

---

## 🧮 Règles EV/ROI (GPI v5.1)

| Règle | Valeur |
|---|---|
| Budget max par course | **5 €** |
| Tickets max | **2** (SP + 1 combiné) |
| Partage SP / Combinés | **60% / 40%** |
| Cap Kelly par cheval | **60 %** |
| EV globale (combinés) | **≥ +40 %** |
| ROI estimé global | **≥ +20 %** |
| Payout min combinés | **> 10 €** |
| Pastille **VERT** si | EV≥40% & ROI≥20% & (si combinés) payout>10€ |

**SP Dutching (placé)** : EV(€) par jambe = `stake * [ p*(odds-1) − (1−p) ]`  
**Combinés (CP/Trio/ZE4)** : via `simulate_wrapper` + calibration `payout_calibration.yaml`.

### 📉 Risque de ruine

`compute_ev_roi` renvoie un champ `risk_of_ruin` qui approxime la probabilité de
perdre l'intégralité du bankroll sur l'ensemble des tickets. L'approximation
utilise `exp(-2 * EV * bankroll / variance)` : une variance élevée ou un
bankroll réduit augmentent ce risque qui tend vers `1`. Pour maintenir un
risque cible (ex. 1 %), ajuster `KELLY_CAP` : diminuer ce cap réduit les mises,
la variance et donc le `risk_of_ruin`.

### 🚀 Optimisation des simulations

`compute_ev_roi` mémorise désormais les probabilités calculées par
`simulate_fn` pour chaque ensemble de `legs`. Ce cache activé par défaut
(`cache_simulations=True`) évite de recalculer des combinaisons identiques et
réduit d'au moins **30 %** le temps CPU mesuré sur des tickets récurrents.
Passer `cache_simulations=False` désactive cette optimisation.

---

## ▶️ Exécutions manuelles (local)

### Générer le planning du jour
```bash
python scripts/online_fetch_zeturf.py \
  --mode planning \
  --out data/planning/$(date +%F).json \
  --sources config/sources.yml
```

### Forcer une fenêtre (ex : R1C3 à H‑30)
```bash
python scripts/runner_chain.py --reunion R1 --course C3 --phase H30 --ttl-hours 6
```

### Lancer l’analyse H‑5
```bash
python scripts/runner_chain.py --reunion R1 --course C3 --phase H5 \
  --budget 5 --calibration config/payout_calibration.yaml
```

### Post‑course : arrivée + MAJ Excel
```bash
python scripts/runner_chain.py --reunion R1 --course C3 --phase RESULT \
  --excel excel/modele_suivi_courses_hippiques.xlsx
```

### Calculer EV/ROI via la CLI
```bash
python cli_ev.py --tickets tickets.json --budget 100 \
  --ev-threshold 5 --roi-threshold 0.2
```

---

## 🧾 Artifacts produits

- `data/snapshots/R1C3/snapshot_H30.json` et `snapshot_H5.json`
- `data/R1C3/analysis_H5.json` (tickets, EV/ROI, pastille)
- `data/R1C3/tracking.csv` (ligne synthèse)
- `data/results/YYYY-MM-DD_arrivees.json`
- `excel/modele_suivi_courses_hippiques.xlsx` (mis à jour)

Extrait `analysis_H5.json` :
```json
{
  "meta": {"reunion":"R1","course":"C3","date":"2025-09-07"},
  "tickets": [
    {"id":"SP1","type":"SP","legs":[{"horse":"6","p":0.38,"odds":2.9}, {"horse":"3","p":0.32,"odds":3.4}],"ev_ratio":0.31},
    {"id":"CP1","type":"CP","legs":["6","3"],"ev_check":{"ev_ratio":0.41,"payout_expected":12.5}}
  ],
  "validation": {
    "sp":{"status":"ok","roi_est":0.31},
    "exotics":{"validated":true},
    "roi_global_est":0.27
  },
  "ev_ok": true,
  "abstain": false
}
```

---

## ✅ Check‑list de mise en route

1. Pousser la structure de dépôt ci‑dessus.  
2. Ajouter **`requirements.txt`** et installer en local (facultatif).  
3. Créer les **Secrets** `DRIVE_FOLDER_ID` & `GOOGLE_CREDENTIALS_JSON`.  
4. Vérifier que les scripts sous `scripts/` existent bien aux bons chemins.  
5. Laisser tourner les 3 workflows (planning, scheduler, results).  
6. Contrôler sur **Actions** les logs d’exécution et la création des JSON/Excel.  

---

## 🛠️ Dépannage (FAQ)

- **Les workflows ne se déclenchent pas** → vérifier le dossier **`.github/workflows/`** (orthographe) et la branche par défaut.  
- **Arrivées non trouvées** → voir logs `get_arrivee_geny.py`, parfois page retardée ; relancer manuellement `post_results.yml`.  
- **Drive non uploadé** → secrets manquants (`DRIVE_FOLDER_ID` / `GOOGLE_CREDENTIALS_JSON`) ou quota Google.  
- **EV combinés = insufficient_data** → calibration absente/vides (`config/payout_calibration.yaml`) ou p_place non enrichies.  
- **Excel non mis à jour** → chemin `--excel` correct ? vérifier permissions du runner (commit autorisé).  

---

## 🔒 Bonnes pratiques

- Ne **jamais** committer de secrets (`credentials.json`, `.env`).  
- En prod GitHub, préférer des **dossiers persistants** (artifacts/Drive) car le runner est éphémère.  
- Ajouter une **tempo** (0.5–1s) dans les fetchs pour éviter un blocage des sites sources.  

---

## © Licence & contact

Projet privé **Analyse Hippique – GPI v5.1**.  
Auteur : Deletrez — Support technique : via issues privées du repo.
