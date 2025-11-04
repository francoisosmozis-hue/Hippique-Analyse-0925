from playwright.sync_api import sync_playwright
import sys, time

def fetch(url: str, wait_ms: int = 1200) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(wait_ms/1000)
        html = page.content()
        browser.close()
        return html

if __name__ == "__main__":
    url = sys.argv[1]
    print(fetch(url))
