import requests
from bs4 import BeautifulSoup
import re

url = "https://www.zeturf.fr/fr/reunion/2025-10-19/R5-Reims"
headers = {'User-Agent': 'Mozilla/5.0'}

try:
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    # Let's try a few selectors

    print("--- Attempt 1: div.courses-list ---")
    course_list_container = soup.find("div", class_="courses-list")
    if course_list_container:
        print("Found container: div.courses-list")
        links = course_list_container.find_all("a", href=re.compile(r"/fr/course/"))
        print(f"Found {len(links)} links in it.")
    else:
        print("Container not found.")

    print("\n--- Attempt 2: div#programmes-courses-right-col ---")
    container2 = soup.find(id="programmes-courses-right-col")
    if container2:
        print("Found container: div#programmes-courses-right-col")
        links = container2.find_all("a", href=re.compile(r"/fr/course/"))
        print(f"Found {len(links)} links in it.")
        for link in links:
            print(link.get('href'))
    else:
        print("Container not found.")

    print("\n--- Attempt 3: Find all links on page ---")
    all_links = soup.find_all("a", href=re.compile(r"/fr/course/"))
    print(f"Found {len(all_links)} links in total on the page.")
    for link in all_links:
        print(link.get('href'))


except requests.RequestException as e:
    print(f"Error fetching URL: {e}")
