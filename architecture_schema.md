```mermaid
graph TD
    subgraph "A) Planification (09:00)"
        A1[Cloud Scheduler @09:00] -->|HTTP POST| A2("service.py: /schedule");
        A2 -->|await| A3("plan.py: build_plan_async()");
        A3 -->|Scrape| A4[www.boturfers.fr];
        A4 -->|Programme du jour| A3;
        A3 -->|Plan des courses| A2;
        A2 -->|Pour chaque course| A5("scheduler.py: schedule_all_races()");
        A5 -->|Crée Tâche H-30| A6[Cloud Tasks];
        A5 -->|Crée Tâche H-5| A6;
    end

    subgraph "B) Analyse (H-30 / H-5)"
        B1[Cloud Tasks] -->|HTTP POST| B2("service.py: /tasks/run-phase");
        B2 -->|Délègue| B3("runner.py: run_course()");
        B3 -->|Orchestre| B4("analysis_pipeline.py: process_single_course_analysis()");
        B4 -->|Scrape| B5[www.boturfers.fr];
        B5 -->|Données de la course| B4;
        B4 -->|Enregistre snapshot| B6("storage.py: save_snapshot()");
        B6 -->|Fichier JSON| B7[GCS Bucket];
        B4 -->|Enregistre métadata| B8("storage.py: save_snapshot_metadata()");
        B8 -->|Référence GCS| B9[Firestore: /races/{id}/snapshots];
        B4 -->|Charge config| B10("storage.py: get_gpi_config()");
        B10 -->|Fichier YAML| B7;
        B4 -->|Génère tickets| B11("pipeline_run.py: generate_tickets()");
        B11 -->|Logique GPI v5.2| B11;
        B11 -->|Décision & Tickets| B4;
        B4 -->|Met à jour document| B12("storage.py: update_race_document()");
        B12 -->|tickets_analysis| B13[Firestore: /races/{id}];
    end

    subgraph "C) Consultation (Utilisateur)"
        C1[Navigateur Web] -->|GET| C2("service.py: /pronostics/ui");
        C2 -->|HTML| C1;
        C1 -->|fetch() JS| C3("service.py: /pronostics?date=...");
        C3 -->|Récupère données| C4("firestore_client.py: get_races_by_date_prefix()");
        C4 -->|Lit collection| C5[Firestore: /races];
        C5 -->|Documents du jour| C4;
        C4 -->|Liste des courses analysées| C3;
        C3 -->|JSON| C1;
    end

    style A1 fill:#DB4437,stroke:#333,stroke-width:2px,color:#fff
    style B1 fill:#DB4437,stroke:#333,stroke-width:2px,color:#fff
    style C1 fill:#4285F4,stroke:#333,stroke-width:2px,color:#fff
    style A4 fill:#0F9D58,stroke:#333,stroke-width:2px,color:#fff
    style B5 fill:#0F9D58,stroke:#333,stroke-width:2px,color:#fff
    style B7 fill:#F4B400,stroke:#333,stroke-width:2px,color:#333
    style B9 fill:#F4B400,stroke:#333,stroke-width:2px,color:#333
    style B13 fill:#F4B400,stroke:#333,stroke-width:2px,color:#333
    style C5 fill:#F4B400,stroke:#333,stroke-width:2px,color:#333
```

### Explication du schéma

1.  **Planification (matin) :** Un `Cloud Scheduler` externe lance le processus en appelant l'endpoint `/schedule`. Le service `FastAPI` utilise `plan.py` pour scraper le programme du jour sur `boturfers.fr`. Ensuite, `scheduler.py` prend ce plan et crée des `Cloud Tasks` pour chaque course, programmées pour s'exécuter à H-30 et H-5.

2.  **Analyse (par course) :** Chaque `Cloud Task` appelle l'endpoint `/tasks/run-phase`. Cet appel déclenche le pipeline d'analyse pour une seule course :
    - `analysis_pipeline.py` orchestre le processus.
    - Il scrape les données détaillées de la course.
    - Les données brutes ("snapshot") sont stockées dans un bucket **GCS** pour archivage.
    - Une référence à ce snapshot et d'autres métadonnées sont stockées dans **Firestore** pour être facilement interrogeables.
    - La logique principale de `pipeline_run.py` est invoquée. Elle utilise les paramètres du fichier `gpi_v52.yml` pour appliquer les règles GPI (EV, ROI, Kelly, etc.) et générer les tickets.
    - Le résultat final de l'analyse (la décision "Play"/"Abstain" et les tickets) est enregistré dans le document principal de la course sur **Firestore**.

3.  **Consultation (utilisateur) :** L'utilisateur accède à la page `/pronostics/ui`. Le JavaScript de la page appelle l'API `/pronostics`. Cet endpoint `FastAPI` interroge **Firestore** pour trouver toutes les courses analysées pour la date demandée et renvoie les résultats au format JSON, que le navigateur affiche.
