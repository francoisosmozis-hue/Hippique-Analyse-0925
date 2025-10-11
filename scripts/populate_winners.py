
import pandas as pd
import argparse
import datetime as dt
import requests
import sys
from typing import List

def get_arrival_from_api(date: str, reunion: int, course: int) -> List[int]:
    """Fetches the arrival from the open-pmu-api."""
    try:
        # L'API attend le format JJ-MM-AAAA
        formatted_date = dt.datetime.strptime(date, "%Y-%m-%d").strftime("%d-%m-%Y")
        api_url = f"https://open-pmu-api.vercel.app/api/arrivees?date={formatted_date}"
        resp = requests.get(api_url, timeout=15)
        resp.raise_for_status()
        api_data = resp.json()
        
        for r in api_data.get('arrivees', []):
            # L'API peut retourner des numéros de réunion en string ou int
            if r.get('reunion') == reunion or str(r.get('reunion')) == str(reunion):
                if r.get('course') == course or str(r.get('course')) == str(course):
                    # L'API retourne une liste de strings, on les convertit en int
                    return [int(x) for x in r.get('arrivee', []) if str(x).isdigit()]
    except Exception as e:
        print(f"Error fetching arrival from API for R{reunion}C{course} on {date}: {e}", file=sys.stderr)
    return []

def main():
    parser = argparse.ArgumentParser(description="Populate the 'gagnant' column in the training dataset.")
    parser.add_argument("--file", required=True, help="Path to the training_data.csv file.")
    args = parser.parse_args()

    print(f"Loading dataset from {args.file}...")
    try:
        df = pd.read_csv(args.file)
    except FileNotFoundError:
        print(f"Error: The file {args.file} was not found.", file=sys.stderr)
        sys.exit(1)

    if 'gagnant' not in df.columns:
        print(f"Error: 'gagnant' column not found in {args.file}.", file=sys.stderr)
        sys.exit(1)

    # S'assurer que les colonnes d'identification sont du bon type
    df['date'] = df['date'].astype(str)
    df['reunion_num'] = df['reunion_num'].astype(int)
    df['course_num'] = df['course_num'].astype(int)

    # Grouper par course unique
    unique_races = df[['date', 'reunion_num', 'course_num']].drop_duplicates()
    print(f"Found {len(unique_races)} unique races to process.")

    winners_populated = 0
    for index, race in unique_races.iterrows():
        date, reunion, course = race['date'], race['reunion_num'], race['course_num']
        print(f"Processing R{reunion}C{course} on {date}...", end='')
        
        arrival = get_arrival_from_api(date, reunion, course)
        if arrival:
            winner_number = arrival[0]
            print(f" -> Winner is {winner_number}")
            
            # Trouver l'index de la ligne correspondante et mettre à jour la colonne 'gagnant'
            winner_index = df[
                (df['date'] == date) &
                (df['reunion_num'] == reunion) &
                (df['course_num'] == course) &
                (df['num'] == winner_number)
            ].index

            if not winner_index.empty:
                df.loc[winner_index, 'gagnant'] = 1
                winners_populated += 1
            else:
                print(f"  -> Warning: Winner {winner_number} not found in dataset for this race.")
        else:
            print(" -> No arrival found.")

    print(f"\nSuccessfully populated {winners_populated} winners in the dataset.")

    # Sauvegarder le DataFrame mis à jour
    df.to_csv(args.file, index=False)
    print(f"Dataset saved to {args.file}")

if __name__ == "__main__":
    main()
