
import requests
import argparse
import json

def explore_sports(api_key):
    """
    Fetches and prints the list of available sports from The Odds API.
    """
    base_url = "https://api.the-odds-api.com"
    
    sports_url = f"{base_url}/v4/sports"
    
    params = {
        "apiKey": api_key,
    }
    
    try:
        response = requests.get(sports_url, params=params, timeout=30)
        response.raise_for_status()
        
        print("Successfully connected to The Odds API.")
        print("Remaining requests for this month:", response.headers.get("x-requests-remaining"))
        print("---")
        
        sports = response.json()
        
        if not sports:
            print("No sports found.")
            return
            
        print(f"Found {len(sports)} sports:")
        print(json.dumps(sports, indent=2))
        
        # Let's find horse racing
        horse_racing_sport = None
        for sport in sports:
            if "horse" in sport.get("title", "").lower() or "racing" in sport.get("title", "").lower():
                horse_racing_sport = sport
                break
        
        if horse_racing_sport:
            print("\n---")
            print("Found a likely candidate for horse racing:")
            print(json.dumps(horse_racing_sport, indent=2))
        else:
            print("\n---")
            print("Could not automatically find a sport key for horse racing in the list.")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while connecting to the API: {e}")
    except json.JSONDecodeError:
        print("Failed to decode the API response. The response was not valid JSON.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explore The Odds API for available sports.")
    parser.add_argument("--api-key", required=True, help="Your API key for The Odds API.")
    args = parser.parse_args()
    
    explore_sports(args.api_key)
