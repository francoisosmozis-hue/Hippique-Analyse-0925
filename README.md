# Analyse Hippique – GPI v5.1 (Budget 5€ / EV+)

Pipeline **pro** pour planifier, capturer H‑30 / H‑5, analyser et consigner chaque course (tickets, EV/ROI, pastille verte/rouge) avec export Google Cloud Storage + mise à jour Excel.

---

## 🔎 Vue d’ensemble

- **09:00 Paris** : génération du **planning du jour** (réunions, courses, horaires, URLs).
- **Scheduler (*/5 min)** : déclenche auto les fenêtres **H‑30** (snapshots cotes + stats) et **H‑5** (analyse GPI v5.1 + tickets).
- **Post‑results (*/15 min)** : récupération **arrivées officielles**, **mise à jour Excel** (ROI réel), **upload GCS**.

**Standards verrouillés** (GPI v5.1) :
- Budget **max 5 €** / course, **2 tickets max** (SP + 1 combiné éventuel, configurable via `MAX_TICKETS_SP`).
- **EV globale ≥ +35 %** et **ROI estimé global ≥ +25 %** (**ROI SP ≥ +10 %**) pour valider le **vert**.
- Combinés uniquement si **payout attendu > 12 €** (calibration).
- **KELLY_FRACTION = 0.5** : moitié de Kelly pour réduire la variance au prix d'une EV moindre; cap 60 % par cheval.
- **MIN_STAKE_SP = 0.10** : mise minimale par ticket SP, évite les micro-mises (réduit variance) mais peut bloquer un peu d'EV.
- **ROUND_TO_SP = 0.10** : arrondi des mises SP à 0,10 €; utiliser `0` pour désactiver l'arrondi sans provoquer de crash tout en conservant le calcul EV/ROI.
- **SHARPE_MIN = 0.5** : seuil minimal de ratio EV/σ; filtre les paris à variance trop élevée.

### Garde-fous opérationnels

- `online_fetch_zeturf.fetch_race_snapshot()` expose l'API de snapshot Python attendue par `runner_chain`. Elle parcourt désormais directement la page publique ZEturf d'une course (ou bascule sur le cache local via `use_cache=True`) puis retourne uniquement les blocs `runners`, `partants`, `market` et `phase` attendus par les consommateurs CLI.
- La phase **H‑5** réessaie automatiquement les collectes `JE`/`chronos` en cas d'absence des CSV, marque la course « non jouable » via `UNPLAYABLE.txt` si la régénération échoue et évite ainsi que le pipeline plante.
- Les combinés sont désormais filtrés strictement dans `pipeline_run.py` : statut `"ok"` obligatoire, EV ≥ +40 % et payout attendu ≥ 10 € sans heuristique. Le runner et le pipeline partagent la même règle, ce qui garantit un comportement homogène en CLI comme dans les automatisations.
- Le seuil d'overround est adapté automatiquement (`1.30` standard désormais aligné sur la garde ROI, `1.25` pour les handicaps plats ouverts ≥ 14 partants) pour réduire les tickets exotiques à faible espérance.

### API `/analyse`

L'API FastAPI expose un endpoint `POST /analyse` (voir `main.py`).

- Le champ optionnel `course_url` permet de transmettre une URL de réunion à scraper.
- Seules les URLs en **HTTPS** et dont le domaine appartient à la liste blanche `zeturf.fr` / `geny.com` (y compris sous-domaines) sont acceptées.
- Toute URL hors de cette liste retourne une erreur **422** avec un message explicite.

---

## 🗂️ Arborescence

```
analyse-hippique/
├─ README.md
├─ requirements.txt
├─ .env.example
├─ gpi_v51.yml
├─ calibration/
│  ├─ payout_calibration.yaml
│  ├─ probabilities.yaml
│  └─ calibrate_simulator.py
├─ config/
│  ├─ sources.yml
│  └─ meetings.json    # exemple de planning (reunion/course/time)
├─ data/
│  ├─ planning/          # programmes du jour (JSON)
│  ├─ snapshots/         # H-30 / H-5 (cotes + stats)
│  ├─ analyses/          # analyses H-5 (tickets + pastille)
│  └─ results/           # arrivées + exports Excel/CSV
├─ excel/
│  └─ modele_suivi_courses_hippiques.xlsx
├─ scripts/
│  ├─ runner_chain.py
│  ├─ fetch_schedule.py
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

### Configuration des sources

Le fichier `config/sources.yml` pointe vers l'API de snapshot Zeturf :

```yaml
zeturf:
  url: "https://www.zeturf.fr/rest/api/race/{course_id}"
```

Remplacez `{course_id}` par l'identifiant numérique de la course avant d'appeler
`scripts/online_fetch_zeturf.py --mode h30` ou `--mode h5`.
Le workflow `gpi_v51.yml` fait cette substitution automatiquement via son entrée
`course_id`. Pour un test local :

```bash
COURSE_ID=123456 sed -i "s/{course_id}/$COURSE_ID/" config/sources.yml
python scripts/online_fetch_zeturf.py --mode h30 --out data/h30/h30.json
```

### Détection robuste de l'heure de départ

`scripts/online_fetch_zeturf.py` récupère désormais l'heure officielle de départ
des courses directement depuis la page publique ZEturf lorsque l'API ne la
fournit pas. Le scraper :

- parcourt les balises `<time>` et les attributs structurés (`data-start-time`,
  `datetime`, etc.) ;
- lit les blocs `application/ld+json` pour capturer les champs `startDate` ou
  `startTime` ;
- applique en dernier ressort une expression régulière tolérante (`21 h 05`,
  `21h05`, `21.05`...).

Les heures sont normalisées au format `HH:MM` avant d'être injectées dans les
snapshots (`meta.start_time` et `start_time`). Cela garantit que le script
`update_excel_planning.py` dispose toujours d'une heure fiable pour l'onglet
Planning.

### Mise à jour automatisée du planning Excel

Le script `scripts/update_excel_planning.py` met à jour l'onglet **Planning**
du classeur `modele_suivi_courses_hippiques.xlsx` à partir des snapshots H‑30
et des analyses H‑5.

Commandes usuelles :

- **Phase H‑30** – traite un répertoire contenant les snapshots collectés :

  ```bash
  python scripts/update_excel_planning.py \
    --phase H30 \
    --in data/meeting \
    --excel modele_suivi_courses_hippiques.xlsx
  ```

- **Phase H‑5** – injecte l'analyse d'une course (tickets, statut, jouable) :

  ```bash
  python scripts/update_excel_planning.py \
    --phase H5 \
    --in data/R4C5 \
    --excel modele_suivi_courses_hippiques.xlsx
  ```

- **Vérifier la jouabilité d'une course** – réutilise le pipeline de garde-fous
  `runner_chain` et affiche à la fois le JSON complet et un verdict lisible :

  ```bash
  python tools/check_course_playable.py --dir data/R4C5
  ```

  Les paramètres de garde (`--budget`, `--overround-max`, `--ev-min-exotic`,
  etc.) sont identiques à ceux du CLI principal et permettent d'ajuster les
  seuils lors des vérifications ponctuelles.

Le script crée l'onglet s'il est absent, garantit la présence des colonnes
standard (Date, Réunion, Course, Hippodrome, Heure, Partants, Discipline,
Statuts H‑30/H‑5, Jouable H‑5, Tickets H‑5, Commentaires) et réalise une mise
à jour en **upsert** sur la clé `(Date, Réunion, Course)` pour éviter les
doublons. Les commandes ci‑dessus peuvent être enchaînées avec un utilitaire
d'upload (ex. `scripts/drive_sync.py`) pour pousser le fichier sur Google
Drive.

### Automatisation GitHub Actions H‑30 / H‑5

Deux workflows dédiés (`.github/workflows/h30.yml` et `.github/workflows/h5.yml`)
permettent d'orchestrer la collecte et l'analyse quotidiennes à partir du
fichier `sources.txt` :

- **08:30 Europe/Paris** → workflow *Planning H-30* :
  - lance `online_fetch_zeturf.py` pour chaque réunion listée ;
  - met à jour l'onglet Planning (phase `H30`) via
    `scripts/update_excel_planning.py` ;
  - publie les snapshots + l'Excel consolidé en tant qu'artifact GitHub Actions
    (et peut synchroniser vers GCS si les variables `GCS_*` sont définies).
- **Toutes les 5 minutes (08:00–20:55 UTC)** → workflow *Planning H-5* :
  - déclenche `scripts/cron_decider.py` pour identifier les courses à H‑5 ;
  - actualise l'onglet Planning (phase `H5`) à partir de la dernière analyse ;
  - uploade les rapports en artifact et propose la même synchronisation GCS.

Un linter dédié (`scripts/lint_sources.py`) est exécuté automatiquement en H‑30
avec `--enforce-today --warn-only` pour détecter :

- URLs manquantes, mal formées ou hors domaine `zeturf.fr` ;
- doublons ;
- absence de la date du jour dans les liens renseignés.

Le job crée un commentaire GitHub en cas d'anomalie et alerte Slack si le
secret `SLACK_WEBHOOK` est défini. Pour transformer ces avertissements en
échecs bloquants, retirer `--warn-only` dans l'étape « Lint sources.txt ».

Le workflow H‑5 propage également les erreurs vers Slack et peut envoyer un
email (via `dawidd6/action-send-mail`) lorsque les secrets `MAIL_*` sont
configurés. Pour tester localement la qualité des sources avant un commit :

```bash
python scripts/lint_sources.py --file sources.txt --enforce-today
```

#### Exemple de flux quotidien

1. **Collecte H‑30**
   - Renseigner `sources.txt` avec une URL ZEturf par réunion.
   - Exécuter la boucle de snapshots :

     ```bash
     export TZ=Europe/Paris
     while read -r url; do
       python online_fetch_zeturf.py --reunion-url "$url" --snapshot H-30 --out data/meeting
     done < sources.txt
     ```

   - Mettre à jour l'Excel :

     ```bash
     python scripts/update_excel_planning.py \
       --phase H30 \
       --in data/meeting \
       --excel modele_suivi_courses_hippiques.xlsx
     ```

2. **Analyse H‑5**
   - Lancer l'analyse (ex. `python analyse_courses_du_jour_enrichie.py`).
   - Actualiser l'onglet Planning avec la course traitée :

     ```bash
     python scripts/update_excel_planning.py \
       --phase H5 \
       --in data/R4C5 \
       --excel modele_suivi_courses_hippiques.xlsx
     ```

3. **Synchronisation Drive (optionnel)**
   - Utiliser l'outil existant pour pousser le fichier mis à jour :

     ```bash
     python scripts/drive_sync.py \
       --push \
       --folder-id "<ID_DOSSIER_DRIVE>" \
       --credentials credentials.json \
       --file modele_suivi_courses_hippiques.xlsx
     ```

Cette séquence garantit que les colonnes Statut H‑30/H‑5, Jouable et Tickets
sont enrichies au fur et à mesure des analyses tout en conservant un historique
cohérent pour le suivi quotidien.
---

## ⚙️ Installation locale

1) **Python 3.12+**
2) Dépendances :
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```
**Ex. de packages** : `pandas`, `openpyxl`, `pyyaml`, `requests`, `google-api-python-client`, `google-auth`, `google-auth-httplib2`, `google-auth-oauthlib` …

> **SciPy facultatif** : si `scipy` n'est pas installé, `optimize_stake_allocation` utilisera un optimiseur de secours plus simple.

3) Variables locales : dupliquez `.env.example` en `.env` et ajustez si besoin.

Variables disponibles :

| Variable | Défaut | Description |
| --- | --- | --- |
| `ALLOW_HEURISTIC` | `0` | désactive les heuristiques de backup (`1` pour les autoriser). |

Afin de tester localement ou en CI, un fichier d'exemple `config/meetings.json`
illustre le format attendu (`reunion`, `course`, `time`).
Un planning réel peut être généré via `python scripts/fetch_schedule.py --out config/meetings.json`.

---

## 🔐 Secrets & Variables GitHub

Dans **Settings → Secrets and variables → Actions** du repo, créer :

**Secrets**
- `GCS_SERVICE_KEY_B64` → clé de service Google Cloud encodée en base64 (`credentials.json`)
- `ZETURF_LOGIN` → identifiant pour la connexion Zeturf
- `ZETURF_PASSWORD` → mot de passe pour la connexion Zeturf
- `PYPI_EXTRA_INDEX` *(optionnel)* → URL d'un dépôt PyPI privé
- `GENY_COOKIE` *(optionnel)* → cookie d'accès pour récupérer les données Geny

**Variables**
- `GCS_BUCKET` → bucket Google Cloud Storage de destination
- `GCS_PREFIX` *(optionnel)* → préfixe appliqué aux objets uploadés (ex: `hippiques/prod`)
- `GOOGLE_CLOUD_PROJECT` *(optionnel)* → projet GCP utilisé pour l'authentification
- `MEETING_URLS` → réunions du jour pour H‑30
- `COURSES_URLS` → cours supplémentaires pour H‑5

> ⚠️ **Sécurité :** ne commitez jamais `credentials.json` ni la valeur de ces secrets et évitez toute fuite (logs, issues, captures d'écran).

---

## 🧰 Workflows GitHub

### 1) `daily_planning.yml` — 09:00 Paris
- Appelle `scripts/online_fetch_zeturf.py --mode planning`
- Écrit `data/planning/YYYY-MM-DD.json`

### 2) `race_scheduler.yml` — toutes les 5 min
- Appelle `scripts/runner_chain.py` avec fenêtres **H‑30** puis **H‑5**.
- **H‑30** : snapshots cotes + stats (JSON).  
-- **H‑5** : enrichissement J/E + chronos (si dispo) → **pipeline** (tickets, EV/ROI) → **pastille** (VERT/ROUGE) → export JSON/CSV → **upload GCS**.

### 3) `post_results.yml` — toutes les 15 min
- `get_arrivee_geny.py` → `data/results/ARRIVEES.json`
- `update_excel_with_results.py` → met à jour `excel/modele_suivi_courses_hippiques.xlsx`
- Upload Excel + résultats sur GCS

### 🧾 Mise à jour de l'onglet « Planning »

Le script `scripts/update_excel_planning.py` assure l'upsert des lignes **H‑30** et **H‑5** dans le classeur `modele_suivi_courses_hippiques.xlsx`.

1. **Snap H‑30** – toutes les réunions françaises du jour :

   ```bash
   export TZ=Europe/Paris
   while read -r URL; do
     python online_fetch_zeturf.py --reunion-url "$URL" --snapshot H-30 --out data/meeting
   done < sources.txt

   python scripts/update_excel_planning.py \
     --phase H30 \
     --in data/meeting \
     --excel modele_suivi_courses_hippiques.xlsx
   ```

   Le script crée l'onglet « Planning » s'il est absent, alimente les colonnes *Date*, *Réunion*, *Course*, *Hippodrome*, *Heure*, *Partants*, *Discipline* et positionne « Collecté » dans *Statut H‑30*.

2. **Snap H‑5** – par course analysée :

   ```bash
   python scripts/update_excel_planning.py \
     --phase H5 \
     --in data/R4C5 \
     --excel modele_suivi_courses_hippiques.xlsx
   ```

   La ligne ciblée est mise à jour avec *Statut H‑5 = Analysé*, le drapeau *Jouable H‑5* (Oui/Non selon `abstain`) et une synthèse compacte des tickets (*Tickets H‑5*). Les colonnes vides sont conservées pour d'éventuels commentaires manuels.
   Le libellé du statut H‑5 peut être personnalisé via l'option `--status-h5` (ex. `--status-h5 "Validé"`).

### Lancer les workflows manuellement

Les trois workflows ci-dessus sont planifiés mais peuvent aussi être déclenchés à la demande depuis l'onglet **Actions** du dépôt
via le bouton **Run workflow** ou en ligne de commande :

```bash
gh workflow run race_scheduler.yml
```

Les fichiers générés apparaissent ensuite sous `data/` et `excel/`.

### Déclenchement via API

Un **Personal Access Token** (`GH_PAT`) disposant des scopes `repo` et `workflow` est requis.

#### Mode H‑30

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer GH_PAT" \
  https://api.github.com/repos/OWNER/REPO/actions/workflows/hippique-pipeline.yml/dispatches \
  -d '{"ref":"main","inputs":{"mode":"h30","date":"YYYY-MM-DD","meeting":"R1","race":"C1","hippodrome":"PARIS-VINCENNES","discipline":"trot","course_id":"123456"}}'
```

#### Mode H‑5

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer GH_PAT" \
  https://api.github.com/repos/OWNER/REPO/actions/workflows/hippique-pipeline.yml/dispatches \
  -d '{"ref":"main","inputs":{"mode":"h5","date":"YYYY-MM-DD","meeting":"R1","race":"C1","hippodrome":"PARIS-VINCENNES","discipline":"trot","course_id":"123456"}}'
```

#### Mode post-course

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer GH_PAT" \
  https://api.github.com/repos/OWNER/REPO/actions/workflows/hippique-pipeline.yml/dispatches \
  -d '{"ref":"main","inputs":{"mode":"post","date":"YYYY-MM-DD","meeting":"R1","race":"C1","hippodrome":"PARIS-VINCENNES","discipline":"trot","course_id":"123456"}}'
```

> Rappel : `date` suit le format `YYYY-MM-DD`. Les champs `meeting` et `race` utilisent la notation `R#/C#` (ex. `R1`, `C5`) et `course_id` est l'identifiant numérique de la course.


### Alertes dans les fichiers de suivi

Chaque course analysée ajoute une ligne dans `data/RxCy/tracking.csv`. Si une colonne `ALERTE_VALUE` est présente, le combiné
associé affiche un EV > 0.5 et un payout attendu > 20 € et mérite une vérification manuelle.

### ☁️ Synchronisation Google Cloud Storage

1. Créez un **compte de service** dans la console Google Cloud et donnez-lui
   l'accès en écriture au bucket cible.
2. Définissez les variables d'environnement suivantes :
   - `GCS_BUCKET` (obligatoire) → nom du bucket de destination ;
   - `GCS_SERVICE_KEY_B64` (obligatoire) → contenu base64 du `credentials.json`
     du compte de service ;
   - `GCS_PREFIX` *(optionnel)* → sous-dossier virtuel (préfixe) où ranger les
     artefacts ;
   - `GOOGLE_CLOUD_PROJECT` *(optionnel)* → projet GCP pour journaliser les
     accès.

Le module `scripts/drive_sync.py` expose `upload_file`, `download_file` et
`push_tree` basés sur `google-cloud-storage`.

```bash
python scripts/drive_sync.py \
  --upload-glob "data/results/**/*.json" \
  --upload-glob "excel/*.xlsx"
```

Plusieurs motifs `--upload-glob` peuvent être fournis.  Pour télécharger un
objet : `python scripts/drive_sync.py --download chemin/objet.json destination.json`.

### Récupérer les données archivées

Pour rapatrier les fichiers `snapshot_*.json` et `analysis*.json` d'une date
précise, utilisez :

```bash
export GCS_BUCKET="<bucket>"
export GCS_SERVICE_KEY_B64="$(base64 -w0 credentials.json)"
python scripts/restore_from_drive.py --date YYYY-MM-DD --dest dossier_sortie
```

Ajoutez éventuellement `GCS_PREFIX` pour cibler un sous-dossier. Les fichiers
correspondants sont téléchargés dans le dossier indiqué par `--dest`.

---

## 🧮 Règles EV/ROI (GPI v5.1)

| Règle | Valeur |
|---|---|
| Budget max par course | **5 €** |
| Tickets max | **2** (SP + 1 combiné) |
| Partage SP / Combinés | **60% / 40%** |
| Cap Kelly par cheval (`KELLY_FRACTION`) | **60 %** |
| EV globale (combinés) | **≥ +35 %** |
| ROI estimé SP | **≥ +10 %** |
| ROI estimé global | **≥ +25 %** |
| Payout min combinés | **> 12 €** |
| Mise minimale SP (`MIN_STAKE_SP`) | **0.10 €** |
| Arrondi mise SP (`ROUND_TO_SP`) | **0.10 €** (`0` désactive l'arrondi sans provoquer d'erreur) |
| Sharpe min (`SHARPE_MIN`) | **0.5** |
| Coefficient de drift des cotes (`DRIFT_COEF`) | **0.05** |
| Coefficient bonus J/E (`JE_BONUS_COEF`) | **0.001** |
| Pastille **VERT** si | EV≥35% & ROI≥25% & (si combinés) payout>12€ |

### Variables de configuration principales

| Clé | Description |
| --- | --- |
| `BUDGET_TOTAL` | Budget maximum alloué par course. |
| `SP_RATIO` | Part du budget dédiée aux paris simples (SP). |
| `COMBO_RATIO` | Part du budget dédiée aux combinés. |
| `EV_MIN_SP` | EV minimale requise pour les tickets SP (ratio du budget SP). |
| `EV_MIN_SP_HOMOGENEOUS` | Seuil EV SP appliqué lorsque le champ est considéré homogène. |
| `EV_MIN_GLOBAL` | EV minimale globale pour valider l'émission des combinés. |
| `ROI_MIN_SP` | ROI minimal attendu pour les tickets simples (10 % par défaut). |
| `ROI_MIN_GLOBAL` | ROI minimal global attendu pour les combinés (25 % par défaut). |
| `MAX_VOL_PAR_CHEVAL` | Fraction maximale du budget sur un seul cheval. |
| `MIN_PAYOUT_COMBOS` | Gain minimal attendu pour autoriser un ticket combiné (12 € par défaut). |
| `EXOTIC_MIN_PAYOUT` | Alias de `MIN_PAYOUT_COMBOS` pour compatibilité. |
| `ALLOW_JE_NA` | Autorise l'absence de stats jockey/entraîneur lors de l'analyse. |
| `SNAPSHOTS` | Phases de collecte des cotes pour le drift (ex. `H30,H5`). |
| `DRIFT_TOP_N` | Nombre maximal de steams/drifts conservés. |
| `DRIFT_MIN_DELTA` | Variation minimale de cote pour être retenue comme drift/steam. |
| `P_TRUE_MIN_SAMPLES` | Historique minimal (échantillons/courses) pour activer le modèle `p_true`. |

> ℹ️ Le pipeline accepte également certains alias conviviaux : `TotalBudget`,
> `simpleShare`, `comboShare` ou `maxStakePerHorse` (et leurs équivalents en
> variables d'environnement `TOTAL_BUDGET`, `SIMPLE_RATIO`, `COMBO_SHARE`,
> `MAX_STAKE_PER_HORSE`) sont automatiquement convertis vers les clés
> officielles `BUDGET_TOTAL`, `SP_RATIO`, `COMBO_RATIO` et `MAX_VOL_PAR_CHEVAL`.


Ces seuils peuvent être surchargés lors de l'exécution du pipeline avec les
options `--ev-global`, `--roi-global` et `--min-payout` :

```bash
python pipeline_run.py analyse \
  --ev-global 0.35 --roi-global 0.25 --min-payout 12 \
  --calibration config/payout_calibration.yaml
```

**SP Dutching (placé)** : EV(€) par jambe = `stake * [ p*(odds-1) − (1−p) ]
**Combinés (CP/Trio/ZE4)** : via `simulate_wrapper` + calibration `payout_calibration.yaml` (par défaut `config/payout_calibration.yaml`, avec repli automatique vers `calibration/payout_calibration.yaml`, surchargeable via `--calibration`).


### Calibration, budget & `ALERTE_VALUE`

- Les fichiers `calibration/payout_calibration.yaml` et `calibration/probabilities.yaml` doivent être présents avant toute
  analyse. Ils calibrent respectivement les gains des combinés et les probabilités de base. Mettre ces fichiers à jour
  régulièrement avec `calibrate_simulator.py` ou `recalibrate_payouts_pro.py`.
- La calibration `calibration/p_true_model.yaml` n'est utilisée que si `n_samples` et `n_races` dépassent `P_TRUE_MIN_SAMPLES`.
  Tant que ce seuil n'est pas atteint, le pipeline revient sur l'heuristique interne : réalimenter le modèle avec davantage de
  courses avant de réactiver la calibration.
- Le budget total (`BUDGET_TOTAL`) est réparti entre paris simples et combinés selon `SP_RATIO` et `COMBO_RATIO`
  (par défaut **60 % / 40 %**). Modifier ces variables pour ajuster la répartition.
- Lorsqu'une combinaison présente à la fois un EV élevé et un payout attendu important, un drapeau `ALERTE_VALUE` est posé
  sur le ticket. Ce flag est propagé jusqu'au `tracking.csv` pour attirer l'attention sur ces cas à surveiller.
### ♻️ Recalibrage des payouts

Le script `recalibrate_payouts_pro.py` met à jour `calibration/payout_calibration.yaml`
à partir de rapports JSON (champ `abs_error_pct`) collectés après les courses.

```bash
python recalibrate_payouts_pro.py --history data/results/*.json \
  --out calibration/payout_calibration.yaml
```

Si l'erreur moyenne dépasse **15 %** pour les combinés (CP/TRIO/ZE4), le
champ `PAUSE_EXOTIQUES` est positionné à `true` afin de bloquer les paris
combinés jusqu'à la prochaine calibration.

### 📊 Closing Line Value (CLV)

Chaque ticket conserve maintenant la cote d'ouverture et la cote de clôture
observée au moment du départ. Le **CLV** est défini comme
`(closing_odds - open_odds) / open_odds`. Un CLV positif signifie que le
marché est allé dans notre sens et corrèle généralement avec un **ROI réel**
supérieur.

### 📉 Risque de ruine

`compute_ev_roi` renvoie un champ `risk_of_ruin` qui approxime la probabilité de
perdre l'intégralité du bankroll sur l'ensemble des tickets. L'approximation
utilise `exp(-2 * EV * bankroll / variance)` : une variance élevée ou un
bankroll réduit augmentent ce risque qui tend vers `1`. Pour maintenir un
risque cible (ex. 1 %), ajuster `KELLY_CAP` : diminuer ce cap réduit les mises,
la variance et donc le `risk_of_ruin`.

### 🎯 Limite de variance

Un paramètre optionnel `variance_cap` permet de plafonner la volatilité globale.
Si la variance cumulée des tickets dépasse `variance_cap * bankroll^2`, les mises
sont réduites proportionnellement et le panier est signalé comme trop risqué.

### 🤖 Auto‑sélection des tickets

Chaque appel à `compute_ev_roi` renvoie désormais une liste `ticket_metrics` où
chaque ticket est décrit par :

- `kelly_stake` – mise recommandée par Kelly avant plafonnement,
- `stake` – mise réellement engagée après cap `kelly_cap`,
- `ev` – espérance de gain en euros,
- `roi` – retour sur investissement (`ev / stake`),
- `variance` – variance de la mise,
- `clv` – *closing line value*.

Ces métriques permettent d'automatiser la sélection des tickets :
filtrer ceux dont le `roi` ou l'`ev` est négatif, privilégier les meilleurs
rapports `ev/variance` ou encore appliquer des seuils personnalisés avant de
valider l'envoi des tickets.

### 🚀 Optimisation des simulations

`compute_ev_roi` mémorise désormais les probabilités calculées par
`simulate_fn` pour chaque ensemble de `legs`. Ce cache activé par défaut
(`cache_simulations=True`) évite de recalculer des combinaisons identiques et
réduit d'au moins **30 %** le temps CPU mesuré sur des tickets récurrents.
Passer `cache_simulations=False` désactive cette optimisation.

---

## ▶️ Exécutions manuelles (local)

Un `Makefile` simplifie les commandes usuelles : `make venv` prépare l'environnement virtuel, `make test` lance la suite `pytest`, tandis que `make run-h30` et `make run-h5` enveloppent l'appel `analyse_courses_du_jour_enrichie.py` ci-dessous (ex. `URL="https://www.zeturf.fr/fr/course/..."`).

### Générer le planning du jour
```bash
python scripts/online_fetch_zeturf.py \
  --mode planning \
  --out data/planning/$(date +%F).json \
  --sources config/sources.yml
```

### Forcer une fenêtre (ex : R1C3 à H‑30)
# Le dossier doit contenir un snapshot (ex: snapshot_H30.json)
```bash
python scripts/runner_chain.py data/R1C3 --phase H30
```

### Lancer l’analyse H‑5
# Le dossier doit contenir snapshot_H5.json, je_stats.csv, et chronos.csv
```bash
python scripts/runner_chain.py data/R1C3 --phase H5 \
  --budget 5 --calibration calibration/payout_calibration.yaml
```

### Post‑course : arrivée + MAJ Excel
# Le dossier doit contenir arrivee_officielle.json
```bash
python scripts/runner_chain.py data/R1C3 --phase RESULT
```

Le script autonome `post_course.py` accepte désormais l'option `--places`
pour indiquer le nombre de positions rémunérées à considérer (1 par défaut).
Par exemple :

```bash
python post_course.py --arrivee arrivee.json --tickets tickets.json --places 3
```

### Calculer EV/ROI via la CLI
```bash
python cli_ev.py --tickets tickets.json --budget 100 \
  --ev-threshold 5 --roi-threshold 0.2
```

### Calibrer le simulateur
```bash
python calibration/calibrate_simulator.py --results data/results.csv

```
### Analyse des courses du jour (Geny)

#### Usage

```bash
python fetch_reunions_geny.py --date YYYY-MM-DD --out data/reunions.json
python analyse_courses_du_jour_enrichie.py --reunions-file data/reunions.json --budget <B> --kelly <K>
```

Le second script déclenche automatiquement les phases **H30** puis **H5** pour chaque réunion française listée dans `data/reunions.json`.

#### Dépendances

- `beautifulsoup4`
- `requests`

#### Mise à jour du planning Excel

Un utilitaire dédié `scripts/update_excel_planning.py` permet d'alimenter
l'onglet **Planning** du classeur `modele_suivi_courses_hippiques.xlsx`. Le
script gère les phases H-30 (collecte) et H-5 (analyse) en réalisant un
*upsert* basé sur la clé `(Date, Réunion, Course)`.

```bash
# Phase H-30 : collecte de toutes les réunions françaises du jour
export TZ=Europe/Paris
while read -r URL; do
  python online_fetch_zeturf.py --reunion-url "$URL" --snapshot H-30 --out data/meeting
done < sources.txt

python scripts/update_excel_planning.py \
  --phase H30 \
  --in data/meeting \
  --excel modele_suivi_courses_hippiques.xlsx

# Phase H-5 : mise à jour course par course après l'analyse
python scripts/update_excel_planning.py \
  --phase H5 \
  --in data/R4C5 \
  --excel modele_suivi_courses_hippiques.xlsx
```

Les colonnes suivantes sont ajoutées si nécessaire :
`Date`, `Réunion`, `Course`, `Hippodrome`, `Heure`, `Partants`, `Discipline`,
`Statut H-30`, `Statut H-5`, `Jouable H-5`, `Tickets H-5`, `Commentaires`.
La phase H-5 synthétise les tickets au format compact (`SP:3-5@2.0 | CPL:1-3@1.5`)
et alimente les drapeaux `Statut H-5`/`Jouable H-5` selon l'analyse
(`abstain`).

#### Autres usages

- Exemple pour traiter toutes les réunions du jour :
  ```bash
  python analyse_courses_du_jour_enrichie.py --from-geny-today --phase H5 --budget 5
  ```
  Pour lancer l'analyse depuis un fichier de réunions (`fetch_reunions_geny.py`) :
  ```bash
  python analyse_courses_du_jour_enrichie.py --reunions-file data/reunions.json
  ```
- Pour une réunion spécifique issue de ZEturf :
  ```bash
  python analyse_courses_du_jour_enrichie.py --reunion-url https://www.zeturf.fr/fr/reunion/... --phase H5
  ```
  Les sorties sont écrites sous `data/RxCy/` (ex. `data/R1C3/`).
- Pour une course isolée, la fonction `write_snapshot_from_geny` permet d'écrire un snapshot `H30`/`H5`.
- Limitations : les cotes Geny sont chargées dynamiquement et peuvent varier après capture ; aucune authentification n'est requise.

### Smoke test H-5 express

Un utilitaire shell `scripts/smoke_h5.sh` orchestre une analyse H‑5 complète en
pilotant `analyse_courses_du_jour_enrichie.py`, puis vérifie la présence des
principaux artefacts (`analysis_H5.json`, `per_horse_report.csv`,
`tracking.csv`, `snapshot_H5.json`). Les sorties sont écrites dans le dossier
deterministe `out_smoke_h5/`.

```bash
# URL optionnelle (par défaut : réunion de démonstration ZEturf)
scripts/smoke_h5.sh "https://www.zeturf.fr/fr/meeting/2024-09-25/paris-vincennes"

# Ou bien laissez le script utiliser son URL d'exemple
scripts/smoke_h5.sh
```

Le script accepte également la variable d'environnement `PYTHON` pour pointer
vers un interpréteur spécifique et supprime `out_smoke_h5/` avant chaque
exécution afin de fournir un état propre.

---

## 🧾 Artifacts produits

- `data/snapshots/R1C3/snapshot_H30.json` et `snapshot_H5.json`
- `data/R1C3/analysis_H5.json` – méta, tickets (EV/ROI, flags), validation, `ev_ok`, `abstain`
- `data/R1C3/per_horse_report.csv` – rapport par cheval (`num`, `nom`, `p_finale`, `j_rate`, `e_rate`, `chrono_ok`)
- `data/R1C3/tracking.csv` – ligne synthèse (`ALERTE_VALUE` ajouté si alerte)
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

Le fichier `per_horse_report.csv` est sauvegardé dans le même dossier que l'analyse et contient une ligne par partant avec les
colonnes listées ci-dessus.

---

## ✅ Check‑list de mise en route

1. Pousser la structure de dépôt ci‑dessus.  
2. Ajouter **`requirements.txt`** et installer en local (facultatif).  
3. Créer le **Secret** `GCS_SERVICE_KEY_B64` et les **Variables** `GCS_BUCKET` / `GCS_PREFIX` (optionnelle) / `GOOGLE_CLOUD_PROJECT` (optionnelle).
4. Vérifier que les scripts sous `scripts/` existent bien aux bons chemins.  
5. Laisser tourner les 3 workflows (planning, scheduler, results).  
6. Contrôler sur **Actions** les logs d’exécution et la création des JSON/Excel.
7. Tester la synchro GCS : `python scripts/drive_sync.py --upload-glob "data/**/*.json"` puis un `--download` vers un dossier temporaire.
---

## 🛠️ Dépannage (FAQ)

- **Les workflows ne se déclenchent pas** → vérifier le dossier **`.github/workflows/`** (orthographe) et la branche par défaut.  
- **Arrivées non trouvées** → voir logs `get_arrivee_geny.py`, parfois page retardée ; relancer manuellement `post_results.yml`.  
- **Upload GCS manquant** → secrets/variables absents (`GCS_SERVICE_KEY_B64`, `GCS_BUCKET`, `GCS_PREFIX`/`GOOGLE_CLOUD_PROJECT`) ou droits insuffisants sur le bucket. 
- **EV combinés = insufficient_data** → calibration absente/vides (`calibration/payout_calibration.yaml`) ou p_place non enrichies.  
- **Excel non mis à jour** → chemin `--excel` correct ? vérifier permissions du runner (commit autorisé).  

---

## 🔒 Bonnes pratiques

- Ne **jamais** committer de secrets (`credentials.json`, `.env`).  
- En prod GitHub, préférer des **dossiers persistants** (artifacts/GCS) car le runner est éphémère.  
- Ajouter une **tempo** (0.5–1s) dans les fetchs pour éviter un blocage des sites sources.  

---

## © Licence & contact

Projet privé **Analyse Hippique – GPI v5.1**.  
Auteur : Deletrez — Support technique : via issues privées du repo.
