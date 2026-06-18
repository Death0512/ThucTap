"""
fb_manual_unified.py — Manual batch URL scraper (Playwright + GraphQL).
Replaces fb_manual_unified_sb.py (SeleniumBase).
Supports: photo, post, reel, video URLs.
"""

import json
import os
import re
from urllib.parse import urlparse, urlencode, parse_qs

import pw_utils
from scrapling_session import FBSession

COOKIE_FILE = "fb_cookies.json"
OUTPUT_FILE = "fb_manual_scrape.json"
MIN_URLS    = 1
MAX_URLS    = 15


# ── URL type detection ────────────────────────────────────────────────────────

def detect_url_type(url: str) -> str | None:
    if "photo.php" in url or "/photo/" in url or "/photo?" in url:
        return "photo"
    if "/reel/" in url or "/reels/" in url:
        return "reel"
    if "/videos/" in url:
        return "video"
    if "/posts/" in url or "story_fbid" in url or "permalink.php" in url:
        return "post"
    return None


def clean_url(raw: str, url_type: str) -> str:
    if url_type in ("post", "video"):
        return raw.split("?")[0]
    if url_type == "photo" and "permalink.php" not in raw and "?" in raw:
        p  = urlparse(raw)
        qs = parse_qs(p.query)
        kept = {k: v for k, v in qs.items() if k in ("fbid", "set", "id", "story_fbid")}
        base = p.scheme + "://" + p.netloc + p.path
        return base + ("?" + urlencode({k: v[0] for k, v in kept.items()}) if kept else "")
    return raw


def collect_urls_from_user(max_urls: int = MAX_URLS) -> list[dict]:
    print("\n" + "═" * 65)
    print("Facebook Manual Scraper — Photo / Post / Reel / Video")
    print(f"Enter between {MIN_URLS} and {max_urls} Facebook URLs.")
    print("Press ENTER on empty line when done.")
    print("═" * 65)
    urls: list[dict] = []
    while len(urls) < max_urls:
        try:
            raw = input(f"  URL [{len(urls)+1}/{max_urls}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            if len(urls) < MIN_URLS:
                print(f"  Please enter at least {MIN_URLS} URL(s).")
                continue
            break
        if "facebook.com" not in raw:
            print("  Not a Facebook URL — skipped.")
            continue
        url_type = detect_url_type(raw)
        if not url_type:
            print("  Could not detect type (photo/post/reel/video) — skipped.")
            continue
        raw = clean_url(raw, url_type)
        if raw in [u["url"] for u in urls]:
            print("  Duplicate URL — skipped.")
            continue
        urls.append({"url": raw, "type": url_type})
        print(f"  Added [{len(urls)}] [{url_type}] {raw}")
    return urls


# ── Per-type scraper functions ────────────────────────────────────────────────

def _switch_to_all_comments(page):
    page.evaluate("""() => {
        var btns = document.querySelectorAll('div[role="button"],span[role="button"]');
        for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].innerText||'').trim().toLowerCase();
            if (t === 'most relevant' || t === 'newest' || t === 'all comments') {
                btns[i].click(); return;
            }
        }
    }""")
    page.wait_for_timeout(2000)
    page.evaluate("""() => {
        var btns = document.querySelectorAll('div[role="menuitem"],div[role="option"],div[role="button"]');
        for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].innerText||'').trim().toLowerCase();
            if (t === 'all comments' || t.startsWith('all comments')) {
                btns[i].click(); return;
            }
        }
    }""")
    page.wait_for_timeout(2000)


def _load_and_expand_comments(page, scroll_steps: int = 25):
    for _ in range(scroll_steps):
        clicked = pw_utils.expand_comments(page)
        if clicked:
            page.wait_for_timeout(2000)
        pw_utils.scroll_page(page, steps=1, step_px=500, pause_ms=1000)


def scrape_photo(page, url: str, idx: int, total: int) -> dict:
    print(f"\n  [photo] [{idx}/{total}] {url}")

    image_src = None
    date_text = None
    caption   = None
    comments: list[dict] = []

    def _navigate():
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)
        _switch_to_all_comments(page)

    responses = pw_utils.capture_graphql(page, _navigate, timeout_ms=14000, retries=3)
    comments  = pw_utils.extract_comments_from_graphql(responses)

    for p in pw_utils.extract_photos_from_graphql(responses):
        if not image_src and p.get("image_src"):
            image_src = p["image_src"]
        if not date_text and p.get("date_text"):
            date_text = p["date_text"]
        if not caption and p.get("caption"):
            caption = p["caption"]

    # DOM fallbacks
    if not image_src:
        image_src = page.evaluate("""() => {
            var imgs = document.querySelectorAll(
                'div.x6s0dn4.x78zum5.xdt5ytf.xl56j7k.x1n2onr6 img[src*="scontent"]'
            );
            return imgs.length ? imgs[0].src : null;
        }""")
    if not date_text:
        date_text = page.evaluate("""() => {
            var spans = document.querySelectorAll('span[id]');
            for (var i = 0; i < spans.length; i++) {
                if (/^_[rR]_/.test(spans[i].id)) {
                    var t = spans[i].innerText.trim();
                    if (t) return t;
                }
            }
            return null;
        }""")
    if not caption:
        caption = page.evaluate("""() => {
            var m = document.querySelector('[data-ad-comet-preview="message"],[data-ad-preview="message"]');
            return m ? (m.innerText||'').trim()||null : null;
        }""")
    if not comments:
        _load_and_expand_comments(page)
        comments = pw_utils.dom_scrape_comments(page)

    print(f"    image : {(image_src or '')[:70]}  date: {date_text or 'N/A'}  comments: {len(comments)}")
    return {"url": url, "type": "photo", "date": date_text,
            "image_src": image_src, "caption": caption, "comments": comments}


def scrape_post(page, url: str, idx: int, total: int) -> dict:
    print(f"\n  [post] [{idx}/{total}] {url}")

    date_text = None
    caption   = None
    comments: list[dict] = []
    screenshot_path = None

    def _navigate():
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)
        page.evaluate("""() => {
            var btns = document.querySelectorAll('div[role="button"],span[role="button"]');
            for (var i = 0; i < btns.length; i++) {
                var t = (btns[i].innerText||'').trim();
                if (t === 'See more' || t === 'See More') { btns[i].click(); break; }
            }
        }""")
        page.wait_for_timeout(1000)
        _switch_to_all_comments(page)

    responses = pw_utils.capture_graphql(page, _navigate, timeout_ms=14000, retries=3)
    comments  = pw_utils.extract_comments_from_graphql(responses)

    for p in pw_utils.extract_posts_from_graphql(responses):
        if not date_text and p.get("date_text"):
            date_text = p["date_text"]
        if not caption and p.get("caption"):
            caption = p["caption"]

    if not date_text:
        date_text = page.evaluate("""() => {
            var spans = document.querySelectorAll('span[id]');
            for (var i = 0; i < spans.length; i++) {
                if (/^_[rR]_/.test(spans[i].id)) {
                    var t = spans[i].innerText.trim();
                    if (t) return t;
                }
            }
            return null;
        }""")
    if not caption:
        caption = page.evaluate("""() => {
            var c = document.querySelector('div.xdj266r.x14z9mp.xat24cr.x1lziwak.x1vvkbs');
            if (c) return (c.innerText||'').trim()||null;
            var m = document.querySelector('[data-ad-comet-preview="message"],[data-ad-preview="message"]');
            return m ? (m.innerText||'').trim()||null : null;
        }""")

    # Screenshot
    os.makedirs("post_screenshots", exist_ok=True)
    fbid = re.search(r"pfbid(\w+)|/posts/(\w+)|fbid=(\w+)", url)
    name = next((g for g in fbid.groups() if g), str(idx)) if fbid else str(idx)
    spath = os.path.join("post_screenshots", f"post_{name}.png")
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(600)
        page.screenshot(path=spath)
        screenshot_path = spath
    except Exception as e:
        print(f"    Screenshot failed: {e}")

    if not comments:
        _load_and_expand_comments(page)
        comments = pw_utils.dom_scrape_comments(page)

    print(f"    date: {date_text or 'N/A'}  comments: {len(comments)}")
    return {"url": url, "type": "post", "date": date_text,
            "caption": caption, "screenshot_path": screenshot_path, "comments": comments}


def scrape_reel(page, url: str, idx: int, total: int) -> dict:
    print(f"\n  [reel] [{idx}/{total}] {url}")
    comments: list[dict] = []

    def _navigate():
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        page.evaluate("""() => {
            var btns = document.querySelectorAll('[aria-label="Comment"][role="button"]');
            if (btns.length) { btns[0].click(); return; }
        }""")
        page.wait_for_timeout(2000)
        _switch_to_all_comments(page)

    responses = pw_utils.capture_graphql(page, _navigate, timeout_ms=12000, retries=3)
    comments  = pw_utils.extract_comments_from_graphql(responses)

    if not comments:
        _load_and_expand_comments(page)
        comments = pw_utils.dom_scrape_comments(page)

    print(f"    comments: {len(comments)}")
    return {"url": url, "type": "reel", "comments": comments}


def scrape_video(page, url: str, idx: int, total: int) -> dict:
    print(f"\n  [video] [{idx}/{total}] {url}")
    date_text = None
    comments: list[dict] = []

    def _navigate():
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)
        page.evaluate("""() => {
            var btns = document.querySelectorAll('[aria-label="Comment"][role="button"]');
            if (btns.length) { btns[0].click(); return; }
        }""")
        page.wait_for_timeout(2000)
        _switch_to_all_comments(page)

    responses = pw_utils.capture_graphql(page, _navigate, timeout_ms=12000, retries=3)
    comments  = pw_utils.extract_comments_from_graphql(responses)

    for p in pw_utils.extract_posts_from_graphql(responses):
        if not date_text and p.get("date_text"):
            date_text = p["date_text"]

    if not comments:
        _load_and_expand_comments(page)
        comments = pw_utils.dom_scrape_comments(page)

    print(f"    date: {date_text or 'N/A'}  comments: {len(comments)}")
    return {"url": url, "type": "video", "date": date_text, "comments": comments}


SCRAPERS = {
    "photo": scrape_photo,
    "post":  scrape_post,
    "reel":  scrape_reel,
    "video": scrape_video,
}


# ── Main ──────────────────────────────────────────────────────────────────────

def main(MAX_URLS: int = MAX_URLS, urls: list[str] | None = None):
    """
    urls: optional list of URL strings (web-app mode — no input() needed).
    If None, falls back to interactive CLI input.
    """
    if urls is not None:
        url_items: list[dict] = []
        for raw in urls[:MAX_URLS]:
            raw = raw.strip()
            if not raw or "facebook.com" not in raw:
                continue
            url_type = detect_url_type(raw)
            if not url_type:
                print(f"    Could not detect type for: {raw} — skipped")
                continue
            raw = clean_url(raw, url_type)
            url_items.append({"url": raw, "type": url_type})
        print(f"   {len(url_items)} URL(s) loaded from web app")
    else:
        url_items = collect_urls_from_user(MAX_URLS)

    if not url_items:
        print("   No URLs provided. Exiting.")
        return

    results: list[dict] = []

    with FBSession(cookie_file=COOKIE_FILE, headless=True) as page:
        print(f"\n\n{'═'*65}")
        print(f"Scraping {len(url_items)} URL(s)")
        print("═" * 65)

        for i, item in enumerate(url_items, 1):
            url      = item["url"]
            url_type = item["type"]
            scraper  = SCRAPERS[url_type]
            try:
                result = scraper(page, url, i, len(url_items))
                results.append(result)
            except Exception as e:
                print(f"    Error: {e}")
                results.append({"url": url, "type": url_type, "error": str(e)})
            page.wait_for_timeout(2000)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n\n{'═'*65}")
    print("  SUMMARY")
    print("═" * 65)
    icons = {"photo": "📸", "post": "📝", "reel": "🎬", "video": "🎥"}
    for r in results:
        icon = icons.get(r["type"], "🔗")
        print(f"\n  {icon} [{r['type']}] {r['url']}")
        if r.get("date"):
            print(f"     date:     {r['date']}")
        if r.get("caption"):
            print(f"     caption:  {r['caption'][:70]}")
        print(f"     comments: {len(r.get('comments', []))}")
        for c in r.get("comments", []):
            snippet = c["comment_text"][:60] + ("…" if len(c["comment_text"]) > 60 else "")
            print(f"       {c['name']:25s}  {snippet}")

    print(f"\n  Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
