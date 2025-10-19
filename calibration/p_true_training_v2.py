"""
Script d'entraînement v2 pour le modèle p_true, utilisant LightGBM et la validation croisée.

Ce script améliore la version précédente en implémentant un modèle de gradient boosting (LightGBM),
qui est beaucoup plus performant pour les problèmes de classification complexes et non-linéaires
rencontrés dans les courses hippiques.

Il utilise une validation croisée stratifiée (StratifiedKFold) pour s'assurer que le modèle
est robuste, généralise bien sur de nouvelles données et n'est pas sujet au surapprentissage.

Le modèle entraîné (un ensemble de modèles de chaque fold) est sauvegardé avec joblib.

Exemple d'utilisation :
python calibration/p_true_training_v2.py \
    --data-dir data/ \
    --model-out calibration/p_true_model_v2.joblib
"""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

# Import de la fonction d'assemblage de données du script original
from calibration.p_true_training import assemble_history_dataset
from sklearn.metrics import brier_score_loss, log_loss

# --- Définition du conteneur de résultat ---

@dataclass(slots=True)
class LGBMCalibrationResult:
    """Conteneur pour les résultats de l'entraînement du modèle LightGBM."""
    models: list[lgb.LGBMClassifier]
    features: list[str]
    n_samples: int
    n_races: int
    brier_score: float
    log_loss: float
    fitted_at: dt.datetime


# --- Fonction d'entraînement ---

def train_lgbm_cv_model(
    dataset: pd.DataFrame,
    *,
    features: list[str],
    n_splits: int = 5,
    random_state: int = 42,
) -> LGBMCalibrationResult:
    """
    Entraîne un classifieur LightGBM avec validation croisée stratifiée.

    Args:
        dataset: DataFrame contenant les données d'entraînement.
        features: Liste des noms de colonnes à utiliser comme features.
        n_splits: Nombre de folds pour la validation croisée.
        random_state: Graine pour la reproductibilité.

    Returns:
        Un objet LGBMCalibrationResult contenant les modèles entraînés et les métriques.
    """
    df = dataset.dropna(subset=["is_winner"] + features)
    if df.empty:
        raise ValueError("Le jeu de données ne contient aucun échantillon valide.")

    X = df[features].to_numpy()
    y = df["is_winner"].astype(int).to_numpy()

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)

    models = []
    oof_preds = np.zeros(len(df), dtype=float)

    print(f"Début de l'entraînement avec StratifiedKFold ({n_splits} splits)...")

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
        print(f"  - Fold {fold + 1}/{n_splits}")
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]

        model = lgb.LGBMClassifier(
            objective='binary',
            metric='logloss',
            random_state=random_state + fold,
            n_estimators=1000,  # Augmenté pour permettre l'early stopping
            learning_rate=0.05,
            num_leaves=31,
            # Ajoutez d'autres hyperparamètres ici si nécessaire
        )

        model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            eval_metric='logloss',
            callbacks=[lgb.early_stopping(100, verbose=False)],
        )

        preds = model.predict_proba(X_val)[:, 1]
        oof_preds[val_idx] = preds
        models.append(model)

    # Calcul des métriques sur l'ensemble des prédictions "out-of-fold"
    brier = float(brier_score_loss(y, oof_preds))
    loss = float(log_loss(y, oof_preds, labels=[0, 1]))

    print("Entraînement terminé.")
    print(f"Score Brier (OOF): {brier:.4f}")
    print(f"Log Loss (OOF): {loss:.4f}")

    return LGBMCalibrationResult(
        models=models,
        features=features,
        n_samples=len(df),
        n_races=int(df["race_id"].nunique() if "race_id" in df else 0),
        brier_score=brier,
        log_loss=loss,
        fitted_at=dt.datetime.now(dt.timezone.utc),
    )


def serialize_lgbm_models(result: LGBMCalibrationResult, path: Path) -> None:
    """Sauvegarde la liste des modèles entraînés dans un fichier joblib."""
    payload = {
        "models": result.models,
        "features": result.features,
        "metadata": {
            "n_samples": result.n_samples,
            "n_races": result.n_races,
            "brier_score": result.brier_score,
            "log_loss": result.log_loss,
            "fitted_at": result.fitted_at.isoformat(),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, path)
    print(f"Modèle sauvegardé dans : {path}")


# --- Point d'entrée du script ---

def main():
    """Fonction principale pour exécuter le pipeline d'entraînement."""
    parser = argparse.ArgumentParser(
        description="Entraînement du modèle p_true v2 (LightGBM + CV)."
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        type=Path,
        help="Répertoire racine contenant les données historiques des courses (ex: ./data).",
    )
    parser.add_argument(
        "--model-out",
        required=True,
        type=Path,
        help="Chemin du fichier pour sauvegarder le modèle entraîné (ex: calibration/p_true_model_v2.joblib).",
    )
    args = parser.parse_args()

    # 1. Assembler le jeu de données
    print(f"Assemblage du jeu de données depuis : {args.data-dir}")
    try:
        dataset = assemble_history_dataset(args.data_dir)
        print(f"-> {len(dataset)} échantillons trouvés.")
        if dataset.empty:
            print("Le jeu de données est vide. Arrêt.")
            return
    except Exception as e:
        print(f"Erreur lors de l'assemblage des données : {e}")
        return

    # 2. Définir les features et entraîner le modèle
    features = [
        "log_odds",
        "drift",
        "je_total",
        "implied_prob",
        "n_runners",
    ]

    try:
        result = train_lgbm_cv_model(dataset, features=features)
    except ValueError as e:
        print(f"Erreur lors de l'entraînement : {e}")
        return

    # 3. Sauvegarder le modèle
    serialize_lgbm_models(result, args.model_out)

    print("\nNOTE: Assurez-vous que 'lightgbm' et 'joblib' sont dans votre requirements.txt")


if __name__ == "__main__":
    main()
