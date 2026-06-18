"""
refresh_cookies.py — Manual cookie refresh tool using Playwright.
Opens Facebook in a visible browser window, waits for manual login,
then saves the session cookies to fb_cookies.json.
"""

import json
import time
from scrapling_session import FBSession

COOKIE_FILE = "fb_cookies.json"

# Fresh manual login in a stealth headful context (no cookies loaded).
session = FBSession(headless=False, verify_login=False, load_cookies_from_file=False)
page = session.__enter__()
try:
    page.goto("https://www.facebook.com", wait_until="domcontentloaded")

    print("Log into Facebook manually in the browser window...")
    print("You have 60 seconds.")
    time.sleep(60)

    cookies = session.context.cookies()
finally:
    session.__exit__(None, None, None)

with open(COOKIE_FILE, "w", encoding="utf-8") as f:
    json.dump(cookies, f, ensure_ascii=False, indent=2)

names = [c.get("name", "") for c in cookies]
if "c_user" in names:
    print(f"Cookies saved to {COOKIE_FILE} ({len(cookies)} cookies) — session looks active")
else:
    print(f"Cookies saved to {COOKIE_FILE} ({len(cookies)} cookies) — WARNING: c_user not found, may not be logged in")
