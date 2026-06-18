"""
fb_posts.py — Facebook text-post scraper (Playwright + GraphQL).
Replaces fb_posts_sb.py (SeleniumBase).
"""

import json
import os
import re

import pw_utils
from scrapling_session import FBSession

COOKIE_FILE = "fb_cookies.json"
OUTPUT_FILE = "fb_posts.json"


# ── Phase 1 — collect /posts/ URLs ───────────────────────────────────────────

def phase1_collect_urls(page, profile_url: str, max_posts: int) -> list[str]:
    print("\n" + "═" * 65)
    print("PHASE 1 — Collecting post URLs")
    print("═" * 65)

    post_links: list[str] = []
    seen: set[str]        = set()
    scroll_n              = 0
    no_change             = 0
    MAX_SCROLLS           = 60

    gql_responses: list[dict] = []

    def _on_response(response):
        if pw_utils._is_graphql(response.url):
            try:
                gql_responses.append(response.json())
            except Exception:
                pass

    page.on("response", _on_response)
    page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)

    while len(post_links) < max_posts and scroll_n < MAX_SCROLLS:
        # GraphQL extraction
        for p in pw_utils.extract_posts_from_graphql(gql_responses):
            url = p.get("post_url", "")
            if url and profile_url.rstrip("/").split("/")[-1] in url and url not in seen:
                seen.add(url)
                post_links.append(url)
                print(f"  [GQL] [{len(post_links)}] {url}")
                if len(post_links) >= max_posts:
                    break

        # DOM fallback
        for url in pw_utils.dom_scrape_post_links(page):
            if profile_url.rstrip("/").split("/")[-1] in url and url not in seen:
                seen.add(url)
                post_links.append(url)
                print(f"  [DOM] [{len(post_links)}] {url}")
                if len(post_links) >= max_posts:
                    break

        print(f"  scroll #{scroll_n}  total: {len(post_links)}")
        if len(post_links) >= max_posts:
            break

        prev = len(post_links)
        pw_utils.scroll_page(page, steps=4, step_px=300, pause_ms=800)
        page.wait_for_timeout(2000)
        scroll_n += 1

        if len(post_links) == prev:
            no_change += 1
        else:
            no_change = 0

        if no_change >= 8:
            print("  No new posts for 8 scrolls — stopping")
            break

    page.remove_listener("response", _on_response)
    print(f"\n  Total posts found: {len(post_links)}")
    return post_links


# ── Screenshot helper ─────────────────────────────────────────────────────────

def take_screenshot(page, post_url: str, idx: int) -> str | None:
    os.makedirs("post_screenshots", exist_ok=True)
    fbid = re.search(r"pfbid(\w+)|/posts/(\w+)|fbid=(\w+)", post_url)
    name = next((g for g in fbid.groups() if g), str(idx)) if fbid else str(idx)
    filepath = os.path.join("post_screenshots", f"post_{name}.png")
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
        page.screenshot(path=filepath, full_page=False)
        print(f"    Screenshot: {filepath}")
        return filepath
    except Exception as e:
        print(f"    Screenshot failed: {e}")
        return None


# ── Phase 2 — scrape each post ────────────────────────────────────────────────

def phase2_scrape_post(page, post_url: str, idx: int, total: int) -> dict:
    print(f"\n  [{idx}/{total}] {post_url}")

    date_text:       str | None  = None
    caption:         str | None  = None
    screenshot_path: str | None  = None
    comments:        list[dict]  = []

    def _navigate():
        page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)
        # Expand "See more"
        page.evaluate("""() => {
            var btns = document.querySelectorAll('div[role="button"],span[role="button"]');
            for (var i = 0; i < btns.length; i++) {
                var t = (btns[i].innerText||'').trim();
                if (t === 'See more' || t === 'See More') { btns[i].click(); break; }
            }
        }""")
        page.wait_for_timeout(1000)
        # Switch to All Comments
        page.evaluate("""() => {
            var btns = document.querySelectorAll('div[role="button"],span[role="button"]');
            for (var i = 0; i < btns.length; i++) {
                var t = (btns[i].innerText||'').trim().toLowerCase();
                if (t === 'most relevant' || t === 'all comments') { btns[i].click(); return; }
            }
        }""")
        page.wait_for_timeout(2000)
        page.evaluate("""() => {
            var btns = document.querySelectorAll('div[role="menuitem"],div[role="option"]');
            for (var i = 0; i < btns.length; i++) {
                var t = (btns[i].innerText||'').trim().toLowerCase();
                if (t === 'all comments' || t.startsWith('all comments')) { btns[i].click(); return; }
            }
        }""")
        page.wait_for_timeout(2000)

    responses = pw_utils.capture_graphql(
        page,
        trigger_fn=_navigate,
        filter_fn=None,
        timeout_ms=14000,
        retries=3,
    )

    # Extract from GraphQL
    comments  = pw_utils.extract_comments_from_graphql(responses)
    gql_posts = pw_utils.extract_posts_from_graphql(responses)
    for p in gql_posts:
        if not date_text and p.get("date_text"):
            date_text = p["date_text"]
        if not caption and p.get("caption"):
            caption = p["caption"]

    # DOM fallback for date
    if not date_text:
        date_text = page.evaluate("""() => {
            var allSpans = document.querySelectorAll('span[id]');
            for (var i = 0; i < allSpans.length; i++) {
                if (/^_[rR]_/.test(allSpans[i].id)) {
                    var t = allSpans[i].innerText.trim();
                    if (t && t.length > 0) return t;
                }
            }
            return null;
        }""")

    # DOM fallback for caption
    if not caption:
        caption = page.evaluate("""() => {
            var c = document.querySelector('div.xdj266r.x14z9mp.xat24cr.x1lziwak.x1vvkbs');
            if (c) return (c.innerText||'').trim() || null;
            var m = document.querySelector('[data-ad-comet-preview="message"],[data-ad-preview="message"]');
            return m ? (m.innerText||'').trim() || null : null;
        }""")

    # Screenshot
    screenshot_path = take_screenshot(page, post_url, idx)

    # DOM fallback for comments — scroll + expand
    if not comments:
        for _ in range(25):
            clicked = pw_utils.expand_comments(page)
            if clicked:
                page.wait_for_timeout(2000)
            pw_utils.scroll_page(page, steps=1, step_px=500, pause_ms=1200)

        comments = pw_utils.dom_scrape_comments(page)

    print(f"    date      : {date_text or 'N/A'}")
    print(f"    caption   : {(caption or '')[:80]}")
    print(f"    screenshot: {screenshot_path or 'N/A'}")
    print(f"    comments  : {len(comments)}")

    return {
        "post_url":        post_url,
        "date":            date_text,
        "caption":         caption,
        "screenshot_path": screenshot_path,
        "comments":        comments,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main(profile_url: str = "", max_posts: int = 10):
    if not profile_url:
        profile_url = input("Enter profile URL: ").strip()

    results: list[dict] = []

    with FBSession(cookie_file=COOKIE_FILE, headless=True) as page:
        post_links = phase1_collect_urls(page, profile_url, max_posts)

        print(f"\n\n{'═'*65}")
        print(f"PHASE 2 — Scraping {len(post_links)} posts")
        print("═" * 65)

        for i, post_url in enumerate(post_links, 1):
            try:
                result = phase2_scrape_post(page, post_url, i, len(post_links))
                results.append(result)
            except Exception as e:
                print(f"    Error on post {i}: {e}")
                results.append({
                    "post_url": post_url, "date": None,
                    "caption": None, "screenshot_path": None,
                    "comments": [], "error": str(e)
                })
            page.wait_for_timeout(2000)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n\n{'═'*65}")
    print("SUMMARY")
    print("═" * 65)
    for r in results:
        print(f"\n  {r['post_url']}")
        print(f"     date      : {r.get('date') or 'N/A'}")
        print(f"     screenshot: {r.get('screenshot_path') or 'N/A'}")
        print(f"     comments  : {len(r.get('comments', []))}")
        for c in r.get("comments", []):
            snippet = c["comment_text"][:60] + ("…" if len(c["comment_text"]) > 60 else "")
            print(f"       {c['name']:25s}  {snippet}")

    print(f"\n  Saved to {OUTPUT_FILE}")
    return results


if __name__ == "__main__":
    main()
