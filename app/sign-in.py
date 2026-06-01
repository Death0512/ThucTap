"""
sign-in.py — Manual session verification tool using Playwright.
Loads fb_cookies.json and checks if the session is still active on Facebook.
"""

import json
from playwright.sync_api import sync_playwright
import pw_utils

COOKIE_FILE = "fb_cookies.json"

with sync_playwright() as pw:
    browser, context = pw_utils.launch_browser(pw, headless=False)
    page = context.new_page()

    print("Loading cookies...")
    pw_utils.login(page, COOKIE_FILE)

    current_url = page.url
    page_source = page.content()

    print(f"\nCurrent URL: {current_url}")

    if 'login' in current_url or 'checkpoint' in current_url:
        print("EXPIRED — redirected to login")
    else:
        print("URL looks ok")

    logged_out_signals = ['id="loginbutton"', 'name="login"', '"isLoggedIn":false']
    logged_in_signals  = ['"isLoggedIn":true', 'c_user', '"USER_ID"', 'id="mount_0_0_']

    print("\n--- Checking logged-out signals ---")
    for sig in logged_out_signals:
        found = sig in page_source
        print(f"  {'FOUND' if found else 'not found'}: {sig}")

    print("\n--- Checking logged-in signals ---")
    for sig in logged_in_signals:
        found = sig in page_source
        print(f"  {'FOUND' if found else 'not found'}: {sig}")

    input("\nPress Enter to close browser...")
    browser.close()
