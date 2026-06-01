"""
pw_utils.py — Shared Playwright utilities for BIRDY-EDWARDS scrapers.

Every scraper imports this module for:
  - Browser launch (Chromium, headless, stealth headers)
  - Cookie load/save (fb_cookies.json format)
  - Facebook login via cookies
  - GraphQL response interception with retry
  - Common GraphQL payload parsers (comments, posts, photos, reels, about)
"""

import json
import time
import re
import os
from typing import Any

from playwright.sync_api import sync_playwright, Page, BrowserContext, Response

COOKIE_FILE = "fb_cookies.json"

# ── Browser launch ────────────────────────────────────────────────────────────

def launch_browser(playwright, headless: bool = True):
    """Launch Chromium with realistic stealth args."""
    browser = playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1280,900",
        ]
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    # Mask navigator.webdriver
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
    """)
    return browser, context


# ── Cookie helpers ────────────────────────────────────────────────────────────

def load_cookies(cookie_file: str = COOKIE_FILE) -> list[dict]:
    """Load cookies from fb_cookies.json (Playwright/Cookie-Editor JSON format)."""
    with open(cookie_file, "r", encoding="utf-8") as f:
        return json.load(f)


def inject_cookies(context: BrowserContext, cookies: list[dict]):
    """Inject cookie list into Playwright context."""
    pw_cookies = []
    for c in cookies:
        entry: dict[str, Any] = {
            "name":   c.get("name", ""),
            "value":  c.get("value", ""),
            "domain": c.get("domain", ".facebook.com"),
            "path":   c.get("path", "/"),
        }
        if c.get("expires") and c["expires"] != -1:
            entry["expires"] = float(c["expires"])
        if "httpOnly" in c:
            entry["httpOnly"] = bool(c["httpOnly"])
        if "secure" in c:
            entry["secure"] = bool(c["secure"])
        sameSite = c.get("sameSite", "Lax")
        if sameSite not in ("Strict", "Lax", "None"):
            sameSite = "Lax"
        entry["sameSite"] = sameSite
        pw_cookies.append(entry)
    context.add_cookies(pw_cookies)


def login(page: Page, cookie_file: str = COOKIE_FILE):
    """Navigate to Facebook, inject cookies, verify login."""
    cookies = load_cookies(cookie_file)
    inject_cookies(page.context, cookies)
    page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    print("    [auth] cookies injected")


# ── GraphQL interception ──────────────────────────────────────────────────────

# Facebook GraphQL endpoint patterns
_GQL_PATTERNS = (
    "/api/graphql/",
    "/graphql/",
)

def _is_graphql(url: str) -> bool:
    return any(p in url for p in _GQL_PATTERNS)


def capture_graphql(
    page: Page,
    trigger_fn,
    filter_fn=None,
    max_responses: int = 0,
    timeout_ms: int = 15000,
    retries: int = 3,
) -> list[dict]:
    """
    Execute trigger_fn (navigation / click / scroll) then collect all GraphQL
    JSON responses that pass filter_fn (optional callable(body_dict) -> bool).

    Args:
        page:          active Playwright page
        trigger_fn:    callable() — runs the action that causes GraphQL traffic
        filter_fn:     optional callable(dict) -> bool to keep only relevant responses
        max_responses: stop after N matching responses (0 = collect all until timeout)
        timeout_ms:    how long to wait for responses after trigger
        retries:       how many times to retry if no responses captured

    Returns:
        list of parsed JSON body dicts from matching GraphQL responses
    """
    for attempt in range(1, retries + 1):
        captured: list[dict] = []

        def _on_response(response: Response):
            if not _is_graphql(response.url):
                return
            try:
                body = response.json()
            except Exception:
                try:
                    text = response.text()
                    # FB sometimes sends multiple JSON objects separated by newlines
                    for line in text.splitlines():
                        line = line.strip()
                        if line:
                            try:
                                obj = json.loads(line)
                                if filter_fn is None or filter_fn(obj):
                                    captured.append(obj)
                            except Exception:
                                pass
                    return
                except Exception:
                    return
            if filter_fn is None or filter_fn(body):
                captured.append(body)

        page.on("response", _on_response)
        try:
            trigger_fn()
            # Wait for responses to arrive
            deadline = time.monotonic() + timeout_ms / 1000
            while time.monotonic() < deadline:
                if max_responses and len(captured) >= max_responses:
                    break
                page.wait_for_timeout(200)
        finally:
            page.remove_listener("response", _on_response)

        if captured:
            print(f"    [graphql] captured {len(captured)} responses")
            return captured

        if attempt < retries:
            print(f"    [graphql] no responses (attempt {attempt}/{retries}) — retrying")
            page.wait_for_timeout(3000)

    print(f"    [graphql] no GraphQL responses captured after {retries} retries")
    return []


# ── GraphQL payload parsers ───────────────────────────────────────────────────

def _walk(obj, visitor):
    """Recursively walk any JSON structure calling visitor on each dict."""
    if isinstance(obj, dict):
        visitor(obj)
        for v in obj.values():
            _walk(v, visitor)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, visitor)


def extract_comments_from_graphql(responses: list[dict]) -> list[dict]:
    """
    Parse GraphQL responses and extract top-level comment objects.
    Returns list of {name, profile_url, comment_text}.
    """
    seen: dict[str, dict] = {}

    for resp in responses:
        def visit(node: dict):
            # Comment nodes have message.text + author.name + author.url
            if "feedback" in node or "comment" not in str(node).lower():
                pass

            # Pattern 1: comment node with author + body
            author = node.get("author") or node.get("commenter")
            body   = node.get("body") or node.get("message")
            if author and body:
                name = author.get("name") or (author.get("short_name", ""))
                url  = (author.get("url") or author.get("profile_url") or "").split("?")[0]
                text = body.get("text") or body.get("delight_ranges_text", "")
                if name and url and "facebook.com" in url and url not in seen:
                    seen[url] = {
                        "name":         name,
                        "profile_url":  url,
                        "comment_text": text or "[Non-text comment]",
                    }

            # Pattern 2: node.node with actor
            inner = node.get("node", {})
            if isinstance(inner, dict):
                actor  = inner.get("author") or inner.get("actor")
                ibody  = inner.get("body") or inner.get("message")
                if actor and ibody:
                    name = actor.get("name", "")
                    url  = (actor.get("url") or "").split("?")[0]
                    text = ibody.get("text", "")
                    if name and url and "facebook.com" in url and url not in seen:
                        seen[url] = {
                            "name":         name,
                            "profile_url":  url,
                            "comment_text": text or "[Non-text comment]",
                        }

        _walk(resp, visit)

    return list(seen.values())


def extract_posts_from_graphql(responses: list[dict]) -> list[dict]:
    """
    Parse GraphQL responses for post timeline entries.
    Returns list of {post_url, date_text, caption}.
    """
    seen: set[str] = set()
    posts: list[dict] = []

    for resp in responses:
        def visit(node: dict):
            url = None
            # Story / post_url fields
            for key in ("url", "story_url", "post_url"):
                v = node.get(key, "")
                if v and "facebook.com" in v and (
                    "/posts/" in v or "story_fbid" in v or "permalink.php" in v
                ):
                    url = v.split("?")[0]
                    break
            if not url or url in seen:
                return
            seen.add(url)

            # Date
            creation_time = node.get("creation_time") or node.get("publish_time")
            date_text = None
            if creation_time:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromtimestamp(int(creation_time), tz=timezone.utc)
                    date_text = dt.strftime("%-d %B %Y")
                except Exception:
                    pass

            # Caption / message
            msg = node.get("message") or node.get("body")
            caption = None
            if isinstance(msg, dict):
                caption = msg.get("text")
            elif isinstance(msg, str):
                caption = msg

            posts.append({
                "post_url":  url,
                "date_text": date_text,
                "caption":   caption,
            })

        _walk(resp, visit)

    return posts


def extract_photos_from_graphql(responses: list[dict]) -> list[dict]:
    """
    Parse GraphQL responses for photo nodes.
    Returns list of {photo_url, image_src, date_text, caption}.
    """
    seen: set[str] = set()
    photos: list[dict] = []

    for resp in responses:
        def visit(node: dict):
            # Photo nodes have __typename == "Photo" or media_type == "photo"
            typename = node.get("__typename", "")
            if typename not in ("Photo", "ProfilePhoto") and "photo" not in typename.lower():
                # Also check if node has photo_image key
                if "photo_image" not in node and "image" not in node:
                    return

            # URL of the photo page
            photo_url = None
            for key in ("url", "photo_url", "permalink_url"):
                v = node.get(key, "")
                if v and "facebook.com" in v and ("photo" in v or "fbid" in v):
                    photo_url = v.split("?")[0] + "?" + v.split("?")[1] if "?" in v else v
                    break
            if not photo_url or photo_url in seen:
                return
            seen.add(photo_url)

            # Image src — highest quality available
            image_src = None
            for key in ("photo_image", "image", "full_image", "preferred_image"):
                img = node.get(key)
                if isinstance(img, dict):
                    image_src = img.get("uri") or img.get("src")
                    if image_src:
                        break

            # Date
            creation_time = node.get("creation_time") or node.get("publish_time")
            date_text = None
            if creation_time:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromtimestamp(int(creation_time), tz=timezone.utc)
                    date_text = dt.strftime("%-d %B %Y")
                except Exception:
                    pass

            # Caption
            msg = node.get("message") or node.get("caption")
            caption = None
            if isinstance(msg, dict):
                caption = msg.get("text")
            elif isinstance(msg, str):
                caption = msg

            photos.append({
                "photo_url": photo_url,
                "image_src": image_src,
                "date_text": date_text,
                "caption":   caption,
            })

        _walk(resp, visit)

    return photos


def extract_reels_from_graphql(responses: list[dict]) -> list[dict]:
    """
    Parse GraphQL responses for reel/video nodes.
    Returns list of {reel_url}.
    """
    seen: set[str] = set()
    reels: list[dict] = []

    for resp in responses:
        def visit(node: dict):
            typename = node.get("__typename", "")
            if typename not in ("Video", "Reel") and "video" not in typename.lower() \
                    and "reel" not in typename.lower():
                return

            for key in ("url", "video_url", "permalink_url", "share_url"):
                v = node.get(key, "")
                if v and "facebook.com" in v and ("/reel/" in v or "/videos/" in v):
                    reel_url = v.split("?")[0]
                    if reel_url not in seen:
                        seen.add(reel_url)
                        reels.append({"reel_url": reel_url})
                    return

        _walk(resp, visit)

    return reels


def extract_about_from_graphql(responses: list[dict]) -> list[dict]:
    """
    Parse GraphQL responses for profile about fields.
    Returns list of {section, field_type, label, value, sub_label}.
    """
    fields: list[dict] = []
    seen: set[str] = set()

    for resp in responses:
        def visit(node: dict):
            field_type = node.get("field_type") or node.get("group_key")
            if not field_type:
                return
            title = node.get("title") or node.get("renderer", {}).get("title", {})
            if isinstance(title, dict):
                text = title.get("text", "")
            elif isinstance(title, str):
                text = title
            else:
                text = ""
            if not text:
                return
            key = f"{field_type}:{text}"
            if key in seen:
                return
            seen.add(key)
            fields.append({
                "section":    "graphql",
                "field_type": str(field_type).lower(),
                "label":      str(field_type).replace("_", " ").title(),
                "value":      text,
                "sub_label":  None,
            })

        _walk(resp, visit)

    return fields


# ── DOM fallback helpers ──────────────────────────────────────────────────────

def dom_scrape_comments(page: Page) -> list[dict]:
    """DOM fallback: scrape comment divs the old way."""
    return page.evaluate("""() => {
        var profiles = document.querySelectorAll('div.x1rg5ohu');
        var seen = {};
        profiles.forEach(function(div) {
            var parent = div.parentElement;
            var isReply = false;
            while (parent) {
                if (parent !== div && parent.classList && parent.classList.contains('x1rg5ohu')) {
                    isReply = true; break;
                }
                parent = parent.parentElement;
            }
            if (isReply) return;
            var a = div.querySelector('a[href]');
            if (!a) return;
            var name = (a.innerText || '').trim();
            var raw  = a.href || '';
            var url  = raw.includes('profile.php') ? raw.split('&')[0] : raw.split('?')[0];
            if (!name || name.length < 2) return;
            var bad = ['l.facebook.com','photo.php','story.php','permalink',
                       'share','/posts/','/photos/','/videos/','/hashtag/'];
            for (var b = 0; b < bad.length; b++) { if (url.includes(bad[b])) return; }
            if (seen[url]) return;
            var text = '';
            var spans = div.querySelectorAll('div[dir="auto"] span, span[dir="auto"]');
            for (var i = 0; i < spans.length; i++) {
                var t = (spans[i].innerText || '').trim();
                if (!t || t === name || t.length <= 1) continue;
                if (t.toLowerCase() === 'follow' || t.toLowerCase() === 'by author') continue;
                if (/^\\d+[smhdwy]$/.test(t)) continue;
                if (/^\\d+\\s+(second|minute|hour|day|week|month|year)s?$/.test(t)) continue;
                text = t; break;
            }
            seen[url] = { name: name, profile_url: url, comment_text: text || '[Non-text comment]' };
        });
        return Object.values(seen);
    }""") or []


def dom_scrape_post_links(page: Page) -> list[str]:
    """DOM fallback: collect post links visible on current page."""
    return page.evaluate("""() => {
        var seen = new Set(); var result = [];
        var links = document.querySelectorAll('a[href*="/posts/"], a[href*="story_fbid"], a[href*="permalink.php"]');
        links.forEach(function(a) {
            var href = a.href || '';
            if (!href.includes('facebook.com') || href.includes('/stories/')) return;
            var clean = href.includes('permalink.php') ? href : href.split('?')[0];
            if (!seen.has(clean)) { seen.add(clean); result.push(clean); }
        });
        return result;
    }""") or []


def dom_scrape_photo_links(page: Page) -> list[dict]:
    """DOM fallback: collect photo links visible on current page."""
    return page.evaluate("""() => {
        var seen = new Set(); var result = [];
        document.querySelectorAll('a').forEach(function(link) {
            var href = link.href || '';
            if (!href.includes('facebook.com') || !href.includes('fbid=')) return;
            if (seen.has(href)) return;
            var type = null;
            if (href.includes('photo.php')) type = 'post_photo';
            else if (href.includes('/photo/') && href.includes('__tn__=%3C')) type = 'profile_picture';
            else if (href.includes('/photo/') && href.includes('set=a.')) type = 'cover_photo';
            if (type) { seen.add(href); result.push({ url: href, type: type }); }
        });
        return result;
    }""") or []


def dom_scrape_reel_links(page: Page) -> list[str]:
    """DOM fallback: collect reel links visible on current page."""
    return page.evaluate(r"""() => {
        var seen = new Set(); var result = [];
        document.querySelectorAll('a').forEach(function(link) {
            var href = link.href || '';
            if (!href.includes('facebook.com')) return;
            if (!href.match(/\/reel\/[a-zA-Z0-9]+/) && !href.match(/\/reels\/[a-zA-Z0-9]+/)) return;
            var clean = href.split('?')[0];
            if (!seen.has(clean)) { seen.add(clean); result.push(clean); }
        });
        return result;
    }""") or []


def scroll_page(page: Page, steps: int = 1, step_px: int = 800, pause_ms: int = 1500):
    """Scroll the page down by step_px × steps, pausing between each."""
    for _ in range(steps):
        page.evaluate(f"window.scrollBy(0, {step_px})")
        page.wait_for_timeout(pause_ms)


def expand_comments(page: Page) -> int:
    """Click any visible 'View more comments' buttons. Returns count clicked."""
    return page.evaluate("""() => {
        var clicked = 0;
        if (!window.__fb_clicked) window.__fb_clicked = new Set();
        var btns = document.querySelectorAll('div[role="button"], span[role="button"]');
        for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].innerText || '').toLowerCase().trim();
            if (!t.includes('view more comment') && !t.includes('more comment')) continue;
            var rect = btns[i].getBoundingClientRect();
            var sig  = t.substring(0, 30) + '|' + Math.round(rect.top) + '|' + Math.round(rect.left);
            if (window.__fb_clicked.has(sig)) continue;
            window.__fb_clicked.add(sig);
            btns[i].click();
            clicked++;
        }
        return clicked;
    }""") or 0
