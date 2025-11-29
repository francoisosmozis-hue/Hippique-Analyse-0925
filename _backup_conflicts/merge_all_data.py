
import json

import pandas as pd

# Load the main dataset
df = pd.read_csv("fr_2025_sept_partants_cotes_arrivees.csv")

# Load the jockey and trainer stats
with open("jockey_stats_provided.json", encoding="utf-8") as f:
    jockey_stats = json.load(f)

with open("trainer_stats_provided.json", encoding="utf-8") as f:
    trainer_stats = json.load(f)

# Prepare columns
df['j_rate'] = 0.0
df['e_rate'] = 0.0

# Normalize names for matching
def normalize_name(name):
    if not isinstance(name, str):
        return ""
    return name.strip().upper()

# Create mapping dictionaries with normalized names
jockey_map = {normalize_name(k): v['j_rate'] for k, v in jockey_stats.items()}
trainer_map = {normalize_name(k): v['e_rate'] for k, v in trainer_stats.items()}

# Apply stats using the map for efficiency
df['j_rate'] = df['jockey'].apply(lambda x: jockey_map.get(normalize_name(x), 0.0))
df['e_rate'] = df['entraineur'].apply(lambda x: trainer_map.get(normalize_name(x), 0.0))

# Handle nulls that might result from failed mappings
df['j_rate'].fillna(0.0, inplace=True)
df['e_rate'].fillna(0.0, inplace=True)

# Save the new enriched dataset
df.to_csv("fr_2025_sept_partants_cotes_arrivees_enriched.csv", index=False)

print("Dataset fully enriched and saved to fr_2025_sept_partants_cotes_arrivees_enriched.csv")
