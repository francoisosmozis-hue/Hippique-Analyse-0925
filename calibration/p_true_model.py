import joblib
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import brier_score_loss
import pandas as pd

class PTrueModel:
    """
    A wrapper for the LightGBM model to predict p_true.
    """
    def __init__(self, params=None):
        if params is None:
            # Des paramètres par défaut, optimisés pour la classification binaire
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