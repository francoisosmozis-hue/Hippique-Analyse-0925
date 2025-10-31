# Format des Données pour le Backtesting

Pour que le framework de backtesting puisse fonctionner, il est nécessaire de fournir un historique des courses dans un format structuré.

## Structure des Dossiers

Chaque course doit être représentée par un dossier nommé `R<reunion>C<course>_<date>`, où la date est au format `YYYY-MM-DD`.

Exemple :
```
backtest_data/
├── R1C1_2023-10-14/
│   ├── snapshot_H-30.json
│   ├── snapshot_H-5.json
│   └── results.json
├── R1C2_2023-10-14/
│   ├── snapshot_H-30.json
│   ├── snapshot_H-5.json
│   └── results.json
└── ...
```

## Format des Fichiers

### `snapshot_H-30.json` et `snapshot_H-5.json`

Ces fichiers doivent contenir les informations sur les partants et leurs cotes, 30 et 5 minutes avant le départ. Le format doit être identique à celui utilisé par le script `online_fetch_zeturf.py`.

Exemple de contenu pour `snapshot_H-5.json` :
```json
{
  "id_course": "12345",
  "phase": "H-5",
  "runners": [
    {"id": "1", "num": "1", "name": "CHEVAL 1", "odds": 5.0},
    {"id": "2", "num": "2", "name": "CHEVAL 2", "odds": 8.2},
    ...
  ],
  "distance": 2100
}
```

### `results.json`

Ce fichier doit contenir les résultats officiels de la course, notamment l'ordre d'arrivée.

Exemple de contenu pour `results.json` :
```json
{
  "arrivee": ["3", "1", "5"]
}
```
