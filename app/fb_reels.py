"""
fb_reels.py — Facebook reel scraper.
Acquisition: Scrapling stealth session (FBSession) driving a Playwright page;
data extracted from intercepted GraphQL responses, adaptive DOM as fallback.
"""

import json
import os

import pw_utils
from scrapling_session import FBSession

COOKIE_FILE = "fb_cookies.json"
OUTPUT_FILE = "fb_reels.json"


def get_reels_url(profile_url: str) -> str:
    profile_url = profile_url.rstrip("/")
    if "profile.php" in profile_url:
        return profile_url + "&sk=reels_tab"
    return profile_url + "/reels"


def phase1_collect_reels(page, profile_url: str, max_reels: int) -> list[str]:
    print("\n" + "═" * 65)
    print("PHASE 1 — Collecting reel URLs")
    print("═" * 65)

    reels_url = get_reels_url(profile_url)
    print(f"Opening: {reels_url}")

    reel_links: list[str] = []
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
    page.goto(reels_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)

    while len(reel_links) < max_reels and scroll_n < MAX_SCROLLS:
        for item in pw_utils.extract_reels_from_graphql(gql_responses):
            url = item.get("reel_url", "")
            if url and url not in seen:
                seen.add(url)
                reel_links.append(url)
                print(f"  [GQL] [{len(reel_links)}] {url}")
                if len(reel_links) >= max_reels:
                    break

        for url in pw_utils.dom_scrape_reel_links(page):
            if url not in seen:
                seen.add(url)
                reel_links.append(url)
                print(f"  [DOM] [{len(reel_links)}] {url}")
                if len(reel_links) >= max_reels:
                    break

        print(f"  scroll #{scroll_n}  total: {len(reel_links)}")
        if len(reel_links) >= max_reels:
            break

        prev = len(reel_links)
        pw_utils.scroll_page(page, steps=4, step_px=300, pause_ms=800)
        page.wait_for_timeout(2000)
        scroll_n += 1

        if len(reel_links) == prev:
            no_change += 1
        else:
            no_change = 0
        if no_change >= 8:
            print("  No new reels for 8 scrolls — stopping")
            break

    page.remove_listener("response", _on_response)
    print(f"\n  Total reels found: {len(reel_links)}")
    return reel_links


def phase2_scrape_reel(page, reel_url: str, idx: int, total: int) -> dict:
    print(f"\n  [{idx}/{total}] {reel_url}")

    comments: list[dict] = []

    def _navigate():
        page.goto(reel_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        pw_utils.click_comment_icon(page)
        pw_utils.switch_to_all_comments(page)

    responses = pw_utils.capture_graphql(
        page,
        trigger_fn=_navigate,
        filter_fn=None,
        timeout_ms=12000,
        retries=3,
    )

    comments = pw_utils.extract_comments_from_graphql(responses)

    if not comments:
        for _ in range(20):
            clicked = pw_utils.expand_comments(page)
            if clicked:
                page.wait_for_timeout(2000)
            pw_utils.scroll_comment_panel(page)
            page.wait_for_timeout(1200)
        comments = pw_utils.dom_scrape_comments(page)

    print(f"    comments: {len(comments)}")
    return {"reel_url": reel_url, "comments": comments}


def main(profile_url: str = "", max_reels: int = 10):
    if not profile_url:
        profile_url = input("Enter profile URL: ").strip()

    results: list[dict] = []

    with FBSession(cookie_file=COOKIE_FILE, headless=True) as page:
        reel_links = phase1_collect_reels(page, profile_url, max_reels)

        print(f"\n\n{'═'*65}")
        print(f"PHASE 2 — Scraping comments for {len(reel_links)} reels")
        print("═" * 65)

        for i, reel_url in enumerate(reel_links, 1):
            try:
                result = phase2_scrape_reel(page, reel_url, i, len(reel_links))
                results.append(result)
            except Exception as e:
                print(f"    Error on reel {i}: {e}")
                results.append({"reel_url": reel_url, "comments": [], "error": str(e)})
            page.wait_for_timeout(2000)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n\n{'═'*65}")
    print("SUMMARY")
    print("═" * 65)
    for r in results:
        print(f"\n  {r['reel_url']}")
        print(f"     comments: {len(r.get('comments', []))}")
        for c in r.get("comments", []):
            snippet = c["comment_text"][:60] + ("…" if len(c["comment_text"]) > 60 else "")
            print(f"       {c['name']:25s}  {snippet}")

    print(f"\n  Saved to {OUTPUT_FILE}")
    return results


if __name__ == "__main__":
    main()
