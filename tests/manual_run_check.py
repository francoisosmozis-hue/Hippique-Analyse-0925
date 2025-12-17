from datetime import datetime

import requests


def test_manual_run_phase():
    # Ensure dummy data exists
    # (Assuming it was created in a previous step)

    payload = {
        "course_url": "https://www.zeturf.fr/fr/course/2025-11-22/R1C1-prix-de-la-course",
        "phase": "H5",
        "date": datetime.now().strftime("%Y-%m-%d")
    }
    try:
        response = requests.post("http://localhost:8080/tasks/run-phase", json=payload, timeout=20)
        print(f"Status Code: {response.status_code}")
        print(f"Response JSON: {response.json()}")
        assert response.status_code == 200
        assert response.json()["ok"] is True
    except requests.exceptions.ConnectionError as e:
        print(f"Connection failed: {e}")
        raise AssertionError("Connection to the server failed.")
    except Exception as e:
        print(f"An error occurred: {e}")
        # If there's a response, print it
        if 'response' in locals():
            print(f"Response content: {response.text}")
        raise AssertionError(f"An unexpected error occurred: {e}")
