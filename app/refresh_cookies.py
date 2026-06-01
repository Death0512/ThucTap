"""
refresh_cookies.py — Manual cookie refresh tool using Playwright.
Opens Facebook in a visible browser window, waits for manual login,
then saves the session cookies to fb_cookies.json.
"""

import json
import time
from playwright.sync_api import sync_playwright
import pw_utils

COOKIE_FILE = "fb_cookies.json"

with sync_playwright() as pw:
    browser, context = pw_utils.launch_browser(pw, headless=False)
    page = context.new_page()

    page.goto("https://www.facebook.com", wait_until="domcontentloaded")

    print("Log into Facebook manually in the browser window...")
    print("You have 60 seconds.")
    time.sleep(60)

    cookies = context.cookies()
    browser.close()

    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)

    names = [c.get("name", "") for c in cookies]
    if "c_user" in names:
        print(f"Cookies saved to {COOKIE_FILE} ({len(cookies)} cookies) — session looks active")
    else:
        print(f"Cookies saved to {COOKIE_FILE} ({len(cookies)} cookies) — WARNING: c_user not found, may not be logged in")
