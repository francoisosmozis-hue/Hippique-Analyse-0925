

import joblib
import lightgbm as lgb
import re
import numpy as np
import pandas as pd

def get_model_metadata() -> dict:
    """
    Retourne les métadonnées du modèle, comme la liste des features attendues.
    """
    features = [
        'age', 'sexe', 'musique_victoires_5_derniers', 'musique_places_5_derniers',
        'musique_disqualifications_5_derniers', 'musique_position_moyenne_5_derniers',
        'cote', 'probabilite_implicite', 'drift_cote'
    ]
    return {'features': features}

def parse_musique(musique_str):
    """Analyse la chaîne 'musique' pour en extraire des features de performance."""
    if not isinstance(musique_str, str):
        return {}
    musique_recente = re.sub(r'\(.*\?)', '', musique_str)
    performances = re.findall(r'(\d+|[A-Z])', musique_recente)
    last_5 = performances[:5]
    
    return {
        'musique_victoires_5_derniers': last_5.count('1'),
        'musique_places_5_derniers': sum(1 for p in last_5 if p in ['1', '2', '3']),
        'musique_disqualifications_5_derniers': sum(1 for p in last_5 if p in ['D', 'A', 'T', 'R']),
        'musique_position_moyenne_5_derniers': np.mean([int(p) for p in last_5 if p.isdigit()] or [-1]),
    }

def compute_runner_features(runner_data: dict, h30_odds: dict, h5_odds: dict) -> dict:
    """
    Calcule les features pour un unique partant.
    """
    features = {}
    
    features['age'] = runner_data.get('age')
    features['sexe'] = 1 if runner_data.get('sexe') == 'M' else 0
    features.update(parse_musique(runner_data.get('musique')))
    
    num = str(runner_data.get('num'))
    cote_h5 = h5_odds.get(num)
    cote_h30 = h30_odds.get(num)

    if cote_h5 and cote_h5 > 1:
        features['cote'] = cote_h5
        features['probabilite_implicite'] = 1 / cote_h5
    else:
        features['cote'] = 999
        features['probabilite_implicite'] = 1 / 999

    if cote_h30 and cote_h5 and cote_h30 > 1 and cote_h5 > 1:
        features['drift_cote'] = (cote_h5 - cote_h30) / cote_h30
    else:
        features['drift_cote'] = 0

    for key, value in features.items():
        if value is None:
            features[key] = -1
            
    return features

def load_p_true_model(filepath: str):
    """Charge un modèle PTrueModel depuis un fichier."""
    return PTrueModel.load(filepath)

def predict_probability(model, features_df: pd.DataFrame):
    """Prédit la probabilité avec le modèle chargé."""
    return model.predict_proba(features_df)

class PTrueModel:
    """
    A wrapper for the LightGBM model to predict p_true.
    """
    def __init__(self, params=None):
        if params is None:
            self.params = {
                'objective': 'binary',
                'metric': 'binary_logloss',
                'boosting_type': 'gbdt',
                'n_estimators': 1000,
                'learning_rate': 0.01,
                'num_leaves': 20,
                'max_depth': 5,
                'seed': 42,
                'n_jobs': -1,
                'verbose': -1,
                'colsample_bytree': 0.7,
                'subsample': 0.7,
            }
        else:
            self.params = params
        self.model = lgb.LGBMClassifier(**self.params)

    def fit(self, X, y, eval_set=None):
        """
        Trains the model.
        Uses early stopping if an evaluation set is provided.
        """
        print("Entraînement du modèle LightGBM...")
        callbacks = [lgb.early_stopping(100, verbose=False)] if eval_set else []
        self.model.fit(X, y, eval_set=eval_set, callbacks=callbacks)
        print("Entraînement terminé.")

    def predict_proba(self, X):
        """
        Predicts probabilities for the positive class.
        """
        return self.model.predict_proba(X)[:, 1]

    def save(self, filepath):
        """
        Saves the trained model to a file.
        """
        print(f"Sauvegarde du modèle dans {filepath}")
        joblib.dump(self.model, filepath)

    @classmethod
    def load(cls, filepath):
        """
        Loads a trained model from a file.
        """
        print(f"Chargement du modèle depuis {filepath}")
        model_instance = cls()
        model_instance.model = joblib.load(filepath)
        return model_instance