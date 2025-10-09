import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import brier_score_loss, roc_auc_score
from calibration.p_true_model import PTrueModel
import os

# Chemin vers les données et le modèle
DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'training_data.csv')
MODEL_OUTPUT_FILE = os.path.join(os.path.dirname(__file__), 'p_true_model.joblib')

def train():
    """
    The main training pipeline.
    """
    print("Démarrage du pipeline d'entraînement...")

    # 1. Chargement des données
    try:
        df = pd.read_csv(DATA_FILE)
        print(f"{len(df)} lignes chargées depuis {DATA_FILE}")
    except FileNotFoundError:
        print(f"ERREUR: Le fichier de données {DATA_FILE} n'a pas été trouvé.")
        print("Veuillez créer ce fichier avec vos données historiques de courses.")
        return

    # 2. Définition des features et de la cible
    features = [
        'age', 'sexe', 'musique_victoires_5_derniers', 'musique_places_5_derniers',
        'musique_disqualifications_5_derniers', 'musique_position_moyenne_5_derniers',
        'cote', 'probabilite_implicite'
    ]
    target = 'gagnant'

    # Le prétraitement est maintenant fait dans build_training_dataset.py
    # df['sexe'] = df['sexe'].astype('category').cat.codes

    # Vérification que toutes les colonnes nécessaires sont présentes
    required_columns = features + [target]
    if not all(col in df.columns for col in required_columns):
        print(f"ERREUR: Colonnes manquantes dans {DATA_FILE}.")
        print(f"Colonnes requises: {required_columns}")
        print(f"Colonnes présentes: {df.columns.tolist()}")
        return

    X = df[features]
    y = df[target]

    # 3. Division des données en ensembles d'entraînement et de test
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # 4. Entraînement du modèle
    pt_model = PTrueModel()
    pt_model.fit(X_train, y_train, eval_set=[(X_test, y_test)])

    # 5. Évaluation du modèle
    print("\n--- Évaluation du Modèle ---")
    predictions = pt_model.predict_proba(X_test)
    brier = brier_score_loss(y_test, predictions)
    auc = roc_auc_score(y_test, predictions)
    print(f"Score Brier sur l'ensemble de test : {brier:.4f} (plus c'est bas, mieux c'est)")
    print(f"Score AUC ROC sur l'ensemble de test : {auc:.4f} (plus c'est haut, mieux c'est)")
    print("---------------------------\n")


    # 6. Sauvegarde du modèle
    pt_model.save(MODEL_OUTPUT_FILE)

if __name__ == "__main__":
    train()