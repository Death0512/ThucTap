"""
fb_photos.py — Facebook photo scraper.
Acquisition: Scrapling stealth session (FBSession) driving a Playwright page;
data extracted from intercepted GraphQL responses, adaptive DOM as fallback.
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


def phase2_scrape_photo(page, photo: dict, idx: int, total: int) -> dict:
    url = photo["url"]
    print(f"\n  [{idx}/{total}] {url}")

    image_src = photo.get("image_src")
    date_text = photo.get("date_text")
    caption   = photo.get("caption")
    comments: list[dict] = []

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

    comments = pw_utils.extract_comments_from_graphql(responses)

    if not image_src or not date_text:
        gql_photos = pw_utils.extract_photos_from_graphql(responses)
        for p in gql_photos:
            if not image_src and p.get("image_src"):
                image_src = p["image_src"]
            if not date_text and p.get("date_text"):
                date_text = p["date_text"]
            if not caption and p.get("caption"):
                caption = p["caption"]

    if not image_src:
        image_src = pw_utils.get_image_src(page)

    if not date_text:
        date_text = pw_utils.get_date_text(page)

    if not caption:
        caption = pw_utils.get_caption(page)

    if not comments:
        pw_utils.switch_to_all_comments(page)
        for _ in range(20):
            clicked = pw_utils.expand_comments(page)
            if clicked:
                page.wait_for_timeout(2000)
            pw_utils.scroll_page(page, steps=1, step_px=400, pause_ms=1200)

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
