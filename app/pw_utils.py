"""
pw_utils.py — Shared GraphQL/DOM extraction utilities for Crawling Bot scrapers.

Browser acquisition (stealth context + cookie auth) lives in
`scrapling_session.FBSession`. This module keeps the extraction layer:
  - Cookie loading (fb_cookies.json format)
  - GraphQL response interception with retry
  - Common GraphQL payload parsers (comments, posts, photos, reels, about)
  - Adaptive DOM helpers — text/role-based, survives FB class churn
All operate on a Playwright `page` (supplied by FBSession) or already-captured JSON.
"""

import json
import re
import time
import os

from playwright.sync_api import Page, Response

COOKIE_FILE = "fb_cookies.json"

# ── Cookie helpers ────────────────────────────────────────────────────────────

def load_cookies(cookie_file: str = COOKIE_FILE) -> list[dict]:
    """Load cookies from fb_cookies.json (Playwright/Cookie-Editor JSON format)."""
    with open(cookie_file, "r", encoding="utf-8") as f:
        return json.load(f)


# ── GraphQL interception ──────────────────────────────────────────────────────

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
    save_to: str = "./captured_responses.json",
) -> list[dict]:
    """
    Execute trigger_fn then collect all GraphQL JSON responses that pass filter_fn.

    If save_to is provided, all captured responses are written to that JSON file
    (overwritten per attempt; final file contains the successful capture).
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
            deadline = time.monotonic() + timeout_ms / 1000
            while time.monotonic() < deadline:
                if max_responses and len(captured) >= max_responses:
                    break
                page.wait_for_timeout(200)
        finally:
            page.remove_listener("response", _on_response)

        if captured:
            print(f"    [graphql] captured {len(captured)} responses")
            if save_to:
                with open(save_to, "w", encoding="utf-8") as f:
                    json.dump(captured, f, ensure_ascii=False, indent=2)
                print(f"    [graphql] saved to {save_to}")
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
    seen: dict[str, dict] = {}
    for resp in responses:
        def visit(node: dict):
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
    seen: set[str] = set()
    posts: list[dict] = []
    for resp in responses:
        def visit(node: dict):
            url = None
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
            creation_time = node.get("creation_time") or node.get("publish_time")
            date_text = None
            if creation_time:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromtimestamp(int(creation_time), tz=timezone.utc)
                    date_text = dt.strftime("%-d %B %Y")
                except Exception:
                    pass
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
    seen: set[str] = set()
    photos: list[dict] = []
    for resp in responses:
        def visit(node: dict):
            typename = node.get("__typename", "")
            if typename not in ("Photo", "ProfilePhoto") and "photo" not in typename.lower():
                if "photo_image" not in node and "image" not in node:
                    return
            photo_url = None
            for key in ("url", "photo_url", "permalink_url"):
                v = node.get(key, "")
                if v and "facebook.com" in v and ("photo" in v or "fbid" in v):
                    photo_url = v.split("?")[0] + "?" + v.split("?")[1] if "?" in v else v
                    break
            if not photo_url or photo_url in seen:
                return
            seen.add(photo_url)
            image_src = None
            for key in ("photo_image", "image", "full_image", "preferred_image"):
                img = node.get(key)
                if isinstance(img, dict):
                    image_src = img.get("uri") or img.get("src")
                    if image_src:
                        break
            creation_time = node.get("creation_time") or node.get("publish_time")
            date_text = None
            if creation_time:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromtimestamp(int(creation_time), tz=timezone.utc)
                    date_text = dt.strftime("%-d %B %Y")
                except Exception:
                    pass
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


# ── Adaptive DOM helpers ──────────────────────────────────────────────────────
# All below use Playwright text/role-based locators — survive FB class churn.

def click_see_more(page: Page) -> bool:
    """Click 'See more' to expand truncated post text."""
    for name in ("See more", "See More"):
        try:
            btn = page.locator(f'[role="button"]:has-text("{name}")').first
            if btn.count() and btn.is_visible():
                btn.click()
                page.wait_for_timeout(800)
                return True
        except Exception:
            pass
    return False


def click_sort_dropdown(page: Page) -> bool:
    """Click the comment-sort dropdown (Most Relevant / Newest / All Comments)."""
    try:
        btn = page.locator('[role="button"]').filter(
            has_text=re.compile(r"most relevant|newest|all comments", re.I)
        ).first
        if btn.count() and btn.is_visible():
            btn.click()
            page.wait_for_timeout(2000)
            return True
    except Exception:
        pass
    return False


def click_all_comments_option(page: Page) -> bool:
    """Select 'All comments' from the opened dropdown menu."""
    try:
        opt = page.get_by_role("menuitem", name="All comments").first
        if opt.count() and opt.is_visible(timeout=3000):
            opt.click()
            page.wait_for_timeout(2000)
            return True
    except Exception:
        pass
    try:
        opt = page.locator('[role="menuitem"]').filter(
            has_text=re.compile(r"all comments", re.I)
        ).first
        if opt.count() and opt.is_visible(timeout=3000):
            opt.click()
            page.wait_for_timeout(2000)
            return True
    except Exception:
        pass
    return False


def switch_to_all_comments(page: Page):
    """Open sort dropdown then select 'All comments'."""
    click_sort_dropdown(page)
    click_all_comments_option(page)


def click_comment_icon(page: Page) -> bool:
    """Click comment icon on a reel/video to open the comment panel."""
    try:
        btn = page.locator('[aria-label="Comment"][role="button"]').first
        if btn.count() and btn.is_visible(timeout=3000):
            btn.click()
            page.wait_for_timeout(2000)
            return True
    except Exception:
        pass
    return False


def expand_comments(page: Page) -> int:
    """Click visible 'View more comments' / 'More comments' buttons."""
    clicked = 0
    if not hasattr(page, '_expanded_sigs'):
        page._expanded_sigs = set()
    try:
        btns = page.locator('[role="button"]').filter(
            has_text=re.compile(r"more comment", re.I)
        )
        for i in range(btns.count()):
            try:
                btn = btns.nth(i)
                if not btn.is_visible():
                    continue
                box = btn.bounding_box()
                if box is None:
                    continue
                key = f"{box['y']:.0f}_{box['x']:.0f}"
                if key in page._expanded_sigs:
                    continue
                page._expanded_sigs.add(key)
                btn.click()
                clicked += 1
                page.wait_for_timeout(600)
            except Exception:
                pass
    except Exception:
        pass
    return clicked


def get_caption(page: Page) -> str | None:
    """Extract post caption using stable data-* attributes."""
    for selector in ('[data-ad-comet-preview="message"]',
                     '[data-ad-preview="message"]'):
        try:
            el = page.locator(selector).first
            if el.count() and el.is_visible():
                return (el.inner_text() or '').strip() or None
        except Exception:
            pass
    return None


def get_image_src(page: Page) -> str | None:
    """Extract photo image src from scontent CDN (stable hostname)."""
    try:
        el = page.locator('img[src*="scontent"]').first
        if el.count():
            return el.get_attribute('src')
    except Exception:
        pass
    return None


def get_date_text(page: Page) -> str | None:
    """Extract post date by matching date-pattern text in spans."""
    date_re = re.compile(
        r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|'
        r'Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|'
        r'Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,4}'
    )
    try:
        el = page.locator('span').filter(has_text=date_re).first
        if el.count():
            raw = (el.inner_text() or '').strip()
            if raw and len(raw) >= 4:
                return raw
    except Exception:
        pass
    return None


def dom_scrape_comments(page: Page) -> list[dict]:
    """
    DOM fallback: scrape comment profiles using JS extraction.
    The extraction logic (tree-walking, sticker/GIF detection, name/URL
    parsing) is inherently JS.  We keep the known-stable container class
    `div.x1rg5ohu` as primary (unchanged for 3+ years) with a semantic
    fallback.
    """
    return page.evaluate("""() => {
        var seen = {};
        // Primary — stable FB comment container class
        var profiles = document.querySelectorAll('div.x1rg5ohu');
        // Semantic fallback: any div containing a profile link
        if (!profiles.length) {
            var linkContainers = [];
            var links = document.querySelectorAll('a[href*="facebook.com/"][role="link"]');
            links.forEach(function(link) {
                var d = link.closest('div[dir="auto"],div.x1rg5ohu,div');
                if (d && linkContainers.indexOf(d) === -1)
                    linkContainers.push(d);
            });
            profiles = linkContainers;
        }
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
            var a = div.querySelector('a[href*="facebook.com"]');
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
    """DOM fallback: collect post URLs from anchor hrefs."""
    return page.evaluate("""() => {
        var seen = new Set(); var result = [];
        var links = document.querySelectorAll(
            'a[href*="/posts/"], a[href*="story_fbid"], a[href*="permalink.php"]'
        );
        links.forEach(function(a) {
            var href = a.href || '';
            if (!href.includes('facebook.com') || href.includes('/stories/')) return;
            var clean = href.includes('permalink.php') ? href : href.split('?')[0];
            if (!seen.has(clean)) { seen.add(clean); result.push(clean); }
        });
        return result;
    }""") or []


def dom_scrape_photo_links(page: Page) -> list[dict]:
    """DOM fallback: collect photo URLs from anchor hrefs."""
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
    """DOM fallback: collect reel URLs from anchor hrefs."""
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
    for _ in range(steps):
        page.evaluate(f"window.scrollBy(0, {step_px})")
        page.wait_for_timeout(pause_ms)


def scroll_comment_panel(page: Page):
    """Scroll the right-side comment panel on reel/video pages."""
    page.evaluate("""() => {
        var els = document.querySelectorAll('*');
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            var s = window.getComputedStyle(el);
            var r = el.getBoundingClientRect();
            if ((s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                r.left > 800 && r.height > 300) {
                el.scrollTop += 400;
                return;
            }
        }
        window.scrollBy(0, 400);
    }""")
