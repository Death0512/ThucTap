"""
fb_photos.py — Facebook photo scraper (Playwright + GraphQL).
Replaces fb_photos_sb.py (SeleniumBase).
"""

import json
import os
import re

import pw_utils
from scrapling_session import FBSession

COOKIE_FILE = "fb_cookies.json"
OUTPUT_FILE = "fb_photos.json"


def get_photos_url(profile_url: str) -> str:
    profile_url = profile_url.rstrip("/")
    if "profile.php" in profile_url:
        return profile_url + "&sk=photos"
    return profile_url + "/photos"


# ── Phase 1 — collect photo page URLs ────────────────────────────────────────

def phase1_collect_photos(page, profile_url: str, max_photos: int) -> list[dict]:
    print("\n" + "═" * 65)
    print("PHASE 1 — Collecting photo URLs")
    print("═" * 65)

    photos_url = get_photos_url(profile_url)
    print(f"Opening: {photos_url}")

    photo_links: list[dict] = []
    seen: set[str]          = set()
    scroll_n                = 0
    no_change               = 0
    MAX_SCROLLS             = 60

    def _navigate():
        page.goto(photos_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)

    # Capture GraphQL responses while the /photos page loads and as we scroll
    responses: list[dict] = []

    def _on_response(response):
        if not pw_utils._is_graphql(response.url):
            return
        try:
            body = response.json()
            responses.append(body)
        except Exception:
            pass

    page.on("response", _on_response)
    _navigate()

    while len(photo_links) < max_photos and scroll_n < MAX_SCROLLS:
        # Try GraphQL first
        gql_photos = pw_utils.extract_photos_from_graphql(responses)
        for p in gql_photos:
            url = p.get("photo_url", "")
            if url and url not in seen:
                seen.add(url)
                photo_links.append({"url": url, "type": "post_photo",
                                    "image_src": p.get("image_src"),
                                    "date_text": p.get("date_text"),
                                    "caption":   p.get("caption")})
                print(f"  [GQL] [{len(photo_links)}] {url}")
                if len(photo_links) >= max_photos:
                    break

        # DOM fallback for any remaining
        dom_items = pw_utils.dom_scrape_photo_links(page)
        for item in dom_items:
            url = item.get("url", "")
            if url and url not in seen:
                seen.add(url)
                photo_links.append({"url": url, "type": item.get("type", "post_photo"),
                                    "image_src": None, "date_text": None, "caption": None})
                print(f"  [DOM] [{len(photo_links)}] {url}")
                if len(photo_links) >= max_photos:
                    break

        print(f"  scroll #{scroll_n}  total: {len(photo_links)}")

        if len(photo_links) >= max_photos:
            break

        prev = len(photo_links)
        pw_utils.scroll_page(page, steps=4, step_px=300, pause_ms=800)
        page.wait_for_timeout(2000)
        scroll_n += 1

        if len(photo_links) == prev:
            no_change += 1
        else:
            no_change = 0

        if no_change >= 8:
            print("  No new photos for 8 scrolls — stopping")
            break

    page.remove_listener("response", _on_response)

    post_photos = [p for p in photo_links if p["type"] == "post_photo"]
    print(f"\n  post_photo={len(post_photos)} / total links={len(photo_links)}")
    return photo_links


# ── Phase 2 — scrape each photo: image + caption + comments ──────────────────

def phase2_scrape_photo(page, photo: dict, idx: int, total: int) -> dict:
    url = photo["url"]
    print(f"\n  [{idx}/{total}] {url}")

    # Pre-filled from GraphQL if available
    image_src = photo.get("image_src")
    date_text = photo.get("date_text")
    caption   = photo.get("caption")
    comments: list[dict] = []

    gql_responses: list[dict] = []

    def _navigate():
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)

    responses = pw_utils.capture_graphql(
        page,
        trigger_fn=_navigate,
        filter_fn=None,
        timeout_ms=12000,
        retries=3,
    )
    gql_responses = responses

    # Extract comments from GraphQL
    comments = pw_utils.extract_comments_from_graphql(gql_responses)

    # Extract image / date / caption from GraphQL if not already set
    if not image_src or not date_text:
        gql_photos = pw_utils.extract_photos_from_graphql(gql_responses)
        for p in gql_photos:
            if not image_src and p.get("image_src"):
                image_src = p["image_src"]
            if not date_text and p.get("date_text"):
                date_text = p["date_text"]
            if not caption and p.get("caption"):
                caption = p["caption"]

    # DOM fallback for image src
    if not image_src:
        image_src = page.evaluate("""() => {
            var imgs = document.querySelectorAll(
                'div.x6s0dn4.x78zum5.xdt5ytf.xl56j7k.x1n2onr6 img[src*="scontent"]'
            );
            return imgs.length ? imgs[0].src : null;
        }""")

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
            var msg = document.querySelector(
                '[data-ad-comet-preview="message"],[data-ad-preview="message"]'
            );
            if (!msg) return null;
            return (msg.innerText || '').trim() || null;
        }""")

    # DOM fallback for comments — switch to All Comments first
    if not comments:
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
            var btns = document.querySelectorAll('div[role="menuitem"],div[role="button"]');
            for (var i = 0; i < btns.length; i++) {
                var t = (btns[i].innerText||'').trim().toLowerCase();
                if (t === 'all comments' || t.startsWith('all comments')) {
                    btns[i].click(); return;
                }
            }
        }""")
        page.wait_for_timeout(2000)

        # Scroll + expand
        for _ in range(20):
            clicked = pw_utils.expand_comments(page)
            if clicked:
                page.wait_for_timeout(2000)
            pw_utils.scroll_page(page, steps=1, step_px=400, pause_ms=1200)
            count = page.evaluate("() => document.querySelectorAll('div.x1rg5ohu').length") or 0
            if count == 0:
                break

        comments = pw_utils.dom_scrape_comments(page)

    print(f"    image_src : {(image_src or '')[:80]}")
    print(f"    date_text : {date_text or 'N/A'}")
    print(f"    caption   : {(caption or '')[:80]}")
    print(f"    comments  : {len(comments)}")

    return {
        "photo_url": url,
        "date":      date_text,
        "image_src": image_src,
        "caption":   caption,
        "comments":  comments,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main(profile_url: str = "", max_photos: int = 12):
    if not profile_url:
        profile_url = input("Enter profile URL: ").strip()

    results: list[dict] = []

    with FBSession(cookie_file=COOKIE_FILE, headless=True) as page:
        all_photos  = phase1_collect_photos(page, profile_url, max_photos)
        post_photos = [p for p in all_photos if p["type"] == "post_photo"]

        print(f"\n\n{'═'*65}")
        print(f"PHASE 2 — Scraping {len(post_photos)} post photos")
        print("═" * 65)

        for i, photo in enumerate(post_photos, 1):
            try:
                result = phase2_scrape_photo(page, photo, i, len(post_photos))
                results.append(result)
            except Exception as e:
                print(f"    Error on photo {i}: {e}")
                results.append({
                    "photo_url": photo["url"],
                    "image_src": None, "caption": None, "comments": [], "error": str(e)
                })
            page.wait_for_timeout(2000)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n\n{'═'*65}")
    print("  SUMMARY")
    print("═" * 65)
    for r in results:
        print(f"\n   {r['photo_url']}")
        print(f"     date     : {r.get('date') or 'N/A'}")
        print(f"     image    : {(r.get('image_src') or '')[:70]}")
        print(f"     caption  : {(r.get('caption') or '')[:70]}")
        print(f"     comments : {len(r.get('comments', []))}")
        for c in r.get("comments", []):
            snippet = c["comment_text"][:60] + ("…" if len(c["comment_text"]) > 60 else "")
            print(f"       {c['name']:25s}  {snippet}")

    print(f"\n  Saved to {OUTPUT_FILE}")
    return results


if __name__ == "__main__":
    main()
