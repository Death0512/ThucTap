"""
scrapling_session.py — Scrapling-backed browser session for Crawling Bot scrapers.

Hybrid design
-------------
Scrapling (DynamicSession) owns the hard parts of acquisition:
  - a persistent, stealth-hardened Chromium context (fingerprint spoofing,
    real user-agent generation, navigator.webdriver masking, etc.)
  - cookie injection / Facebook session auth

The scrapers keep owning extraction:
  - a long-lived Playwright `page` driven across many scroll iterations
  - `page.on("response")` GraphQL interception (see pw_utils.capture_graphql)
  - `page.evaluate()` DOM clicks / expansion / screenshots

Scrapling's `fetch()` opens a short-lived page per call, which does NOT fit the
scroll-driven, accumulate-between-scrolls workflow these scrapers need. So we
use Scrapling only to build the persistent authenticated `context`, then take a
raw Playwright `page` from it (`context.new_page()`) that the existing scraper
loops drive unchanged.

Usage
-----
    from scrapling_session import FBSession

    with FBSession(headless=True) as page:
        # `page` is a normal Playwright sync Page, already logged into Facebook.
        page.goto(profile_url, wait_until="domcontentloaded")
        ...
"""

import json
import os

from scrapling.fetchers import DynamicSession

COOKIE_FILE = "fb_cookies.json"

# Stealth/identity defaults — mirror the previous pw_utils.launch_browser context.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_LOCALE = "en-US"
_TIMEZONE = "America/New_York"

# Extra Chromium flags previously passed to playwright.chromium.launch().
# Scrapling already handles sandbox/dev-shm/automation flags; these are additive.
_EXTRA_FLAGS = [
    "--disable-infobars",
    "--disable-gpu",
    "--window-size=1280,900",
]


def load_cookies(cookie_file: str = COOKIE_FILE) -> list[dict]:
    """Load cookies from fb_cookies.json (Playwright / Cookie-Editor JSON format)."""
    with open(cookie_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_cookies(cookies: list[dict]) -> list[dict]:
    """
    Normalize Cookie-Editor / Playwright cookie dicts into the shape Playwright's
    context.add_cookies() accepts. Identical normalization to the old
    pw_utils.inject_cookies so behaviour is unchanged.
    """
    normalized: list[dict] = []
    for c in cookies:
        entry: dict = {
            "name": c.get("name", ""),
            "value": c.get("value", ""),
            "domain": c.get("domain", ".facebook.com"),
            "path": c.get("path", "/"),
        }
        if c.get("expires") and c["expires"] != -1:
            entry["expires"] = float(c["expires"])
        if "httpOnly" in c:
            entry["httpOnly"] = bool(c["httpOnly"])
        if "secure" in c:
            entry["secure"] = bool(c["secure"])
        same_site = c.get("sameSite", "Lax")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"
        entry["sameSite"] = same_site
        normalized.append(entry)
    return normalized


class FBSession:
    """
    Context manager that yields a persistent, Facebook-authenticated Playwright
    `page` backed by a Scrapling DynamicSession (stealth context + cookies).

    The yielded object is a plain Playwright sync `Page` — every existing
    `page.goto / page.on / page.evaluate / page.screenshot` call works unchanged.
    """

    def __init__(
        self,
        cookie_file: str | None = COOKIE_FILE,
        headless: bool = True,
        verify_login: bool = True,
        load_cookies_from_file: bool = True,
    ):
        """
        :param cookie_file: path to fb_cookies.json. Ignored when
            `load_cookies_from_file=False` (used for fresh-login harvesting).
        :param headless: run Chromium headless (False for manual login flows).
        :param verify_login: warm up the Facebook session after start.
        :param load_cookies_from_file: inject cookies from `cookie_file`. Set
            False to start a clean stealth context for manual login + cookie
            harvesting.
        """
        self.cookie_file = cookie_file
        self.headless = headless
        self.verify_login = verify_login
        self.load_cookies_from_file = load_cookies_from_file
        self._session: DynamicSession | None = None
        self._page = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def __enter__(self):
        cookies = (
            _normalize_cookies(load_cookies(self.cookie_file))
            if self.load_cookies_from_file
            else None
        )

        self._session = DynamicSession(
            headless=self.headless,
            useragent=_USER_AGENT,
            locale=_LOCALE,
            timezone_id=_TIMEZONE,
            cookies=cookies,
            extra_flags=_EXTRA_FLAGS,
            disable_resources=False,
            google_search=False,
        )
        # Starts Playwright + persistent stealth context (cookies applied by
        # Scrapling's context initialization).
        self._session.start()

        # Long-lived page that the scraper loop drives directly.
        self._page = self._session.context.new_page()
        if cookies:
            print("    [auth] scrapling session started — cookies injected")
        else:
            print("    [auth] scrapling session started — clean context (login mode)")

        if self.verify_login and cookies:
            self._login()

        return self._page

    @property
    def page(self):
        """The live Playwright page (valid only inside the `with` block)."""
        return self._page

    @property
    def context(self):
        """The persistent stealth Playwright context (for context.cookies(), etc.)."""
        return self._session.context if self._session else None

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._page is not None:
                self._page.close()
        except Exception:
            pass
        try:
            if self._session is not None:
                self._session.close()
        except Exception:
            pass
        self._page = None
        self._session = None
        return False

    # ── helpers ──────────────────────────────────────────────────────────────

    def _login(self):
        """Warm up the Facebook session (cookies are already in the context)."""
        page = self._page
        page.goto(
            "https://www.facebook.com",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(3000)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        print("    [auth] facebook session warmed")


def open_session(
    cookie_file: str = COOKIE_FILE,
    headless: bool = True,
    verify_login: bool = True,
) -> FBSession:
    """Convenience factory mirroring the `with FBSession(...) as page:` pattern."""
    return FBSession(cookie_file=cookie_file, headless=headless, verify_login=verify_login)
