"""
fb_about.py — Facebook profile About scraper.
Acquisition: Scrapling stealth session (FBSession) driving a Playwright page;
data extracted from intercepted GraphQL responses, DOM as fallback.
"""

import json
import re
import os

import pw_utils
from scrapling_session import FBSession

COOKIE_FILE  = "fb_cookies.json"
OUTPUT_FILE  = "fb_about.json"

DIRECTORY_SECTIONS = [
    "directory_personal_details",
    "directory_work",
    "directory_education",
    "directory_intro",
    "activities",
    "directory_names",
]

FIELD_LABELS = {
    "current_city":   "Current City",
    "hometown":       "Hometown",
    "relationship":   "Relationship",
    "family":         "Family Member",
    "work":           "Work",
    "employer":       "Employer",
    "college":        "College",
    "high_school":    "High School",
    "education":      "Education",
    "intro":          "Introduction",
    "hobby":          "Hobby",
    "hobbies":        "Hobbies",
    "nickname":       "Nickname",
    "other_name":     "Other Name",
    "name":           "Name",
    "birth_date":     "Birth Date",
    "birthday":       "Birthday",
    "gender":         "Gender",
    "languages":      "Languages",
    "language":       "Language",
    "political_view": "Political View",
    "religious_view": "Religious View",
    "website":        "Website",
    "address":        "Address",
}


def decode_unicode(val: str) -> str:
    if not val or not isinstance(val, str):
        return val
    try:
        return val.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    except Exception:
        try:
            return json.loads(f'"{val}"')
        except Exception:
            return val


# ── DOM page-source parsers (retained as fallback) ───────────────────────────

def parse_page_source(source: str, section: str) -> list[dict]:
    results = []
    seen_keys: set[str] = set()
    main_pattern = re.compile(
        r'"field_type"\s*:\s*"([^"]+)"'
        r'.{0,300}?'
        r'"title"\s*:\s*\{'
        r'[^}]{0,300}?'
        r'"text"\s*:\s*"([^"]+)"',
        re.DOTALL
    )
    label_pattern = re.compile(
        r'"list_items"\s*:\s*\[\s*\{'
        r'[^}]{0,200}?'
        r'"text"\s*:\s*\{'
        r'[^}]{0,200}?'
        r'"text"\s*:\s*"([^"]+)"',
        re.DOTALL
    )
    for m in main_pattern.finditer(source):
        field_type = m.group(1)
        value      = decode_unicode(m.group(2))
        if field_type in ("MEDIUM", "HIGH", "LOW") or len(field_type) > 50:
            continue
        key = f"{field_type}:{value}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        label = FIELD_LABELS.get(field_type, field_type.replace("_", " ").title())
        results.append({
            "section":    section,
            "field_type": field_type,
            "label":      label,
            "value":      value,
            "sub_label":  None,
        })
    sub_labels = label_pattern.findall(source)
    sub_idx = 0
    for r in results:
        if r["field_type"] in ("family", "relationship") and sub_idx < len(sub_labels):
            r["sub_label"] = sub_labels[sub_idx]
            sub_idx += 1
    return results


def parse_directory_items(source: str, section: str) -> list[dict]:
    results = []
    seen: set[str] = set()
    pattern = re.compile(
        r'"group_key"\s*:\s*"([^"]+)"'
        r'.{0,500}?'
        r'"renderer"\s*:\s*\{'
        r'.{0,300}?'
        r'"title"\s*:\s*\{'
        r'.{0,200}?'
        r'"text"\s*:\s*"([^"]+)"',
        re.DOTALL
    )
    for m in pattern.finditer(source):
        group_key = m.group(1)
        value     = decode_unicode(m.group(2))
        key = f"{group_key}:{value}"
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "section":    section,
            "field_type": group_key.lower(),
            "label":      group_key.replace("_", " ").title(),
            "value":      value,
            "sub_label":  None,
        })
    return results


def get_directory_url(profile_url: str, section: str) -> str:
    profile_url = profile_url.rstrip("/")
    if "profile.php" in profile_url:
        return profile_url + f"&sk={section}"
    return profile_url + f"/{section}"


# ── Main ──────────────────────────────────────────────────────────────────────

def main(profile_url: str = ""):
    if not profile_url:
        profile_url = input("Enter profile URL: ").strip()

    print("\n" + "═" * 65)
    print("Facebook About Scraper (Scrapling + GraphQL)")
    print(f"Profile: {profile_url}")
    print("═" * 65)

    all_fields: list[dict] = []
    owner_name: str | None = None
    is_locked              = False

    with FBSession(cookie_file=COOKIE_FILE, headless=True) as page:
        # Step 1 — Profile page: owner name + locked check
        print(f"\n   Checking profile...")
        page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        owner_name = page.evaluate("""() => {
            var sels = ['h1 span', '[data-overviewsection] h1'];
            for (var i = 0; i < sels.length; i++) {
                var el = document.querySelector(sels[i]);
                if (el) { var n = (el.innerText||'').trim(); if (n.length>1) return n; }
            }
            var h1s = document.querySelectorAll('h1');
            var skip = ['Notifications','Facebook','Menu','Search','Home'];
            for (var j = 0; j < h1s.length; j++) {
                var n = (h1s[j].innerText||'').trim();
                if (skip.indexOf(n) === -1 && n.length > 1) return n;
            }
            var meta = document.querySelector('meta[property="og:title"]');
            if (meta) return (meta.getAttribute('content')||'').trim() || null;
            return null;
        }""")
        print(f"   Owner name: {owner_name or 'NOT FOUND'}")

        is_locked = page.evaluate("""() => {
            var indicators = ['This account is private','Add friend to see',
                              'profile is locked','Add as friend to see','only visible to friends'];
            var body = (document.body.innerText||'').toLowerCase();
            for (var i = 0; i < indicators.length; i++) {
                if (body.includes(indicators[i].toLowerCase())) return true;
            }
            return false;
        }""") or False
        print(f"   Locked: {is_locked}")

        # Step 2 — Scrape each about section
        for section in DIRECTORY_SECTIONS:
            url = get_directory_url(profile_url, section)
            print(f"\n   [{section}]  {url}")

            # Intercept GraphQL while navigating
            gql_fields: list[dict] = []

            def _navigate():
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)

            responses = pw_utils.capture_graphql(
                page,
                trigger_fn=_navigate,
                filter_fn=lambda b: any(
                    k in str(b) for k in ("field_type", "group_key", "directory")
                ),
                timeout_ms=8000,
                retries=3,
            )

            if responses:
                gql_fields = pw_utils.extract_about_from_graphql(responses)
                print(f"     GraphQL: {len(gql_fields)} fields")

            if not gql_fields:
                # DOM / page-source fallback
                print(f"     Falling back to page-source parser")
                source = page.content()
                if section == "activities":
                    gql_fields = parse_directory_items(source, section)
                else:
                    gql_fields = parse_page_source(source, section)

            # Fix field labels and sections
            for f in gql_fields:
                f["section"] = section
                if f["field_type"] in FIELD_LABELS:
                    f["label"] = FIELD_LABELS[f["field_type"]]

            if gql_fields:
                for f in gql_fields:
                    sub = f" ({f['sub_label']})" if f.get("sub_label") else ""
                    print(f"     {f['label']:25s} → {f['value']}{sub}")
                all_fields.extend(gql_fields)
            else:
                print(f"     No data found")

    # Build output
    output: dict = {
        "profile_url": profile_url,
        "owner_name":  owner_name,
        "is_locked":   is_locked,
        "sections":    {},
    }
    for f in all_fields:
        sec = f["section"]
        if sec not in output["sections"]:
            output["sections"][sec] = []
        entry = {"field_type": f["field_type"], "label": f["label"], "value": f["value"]}
        if f.get("sub_label"):
            entry["sub_label"] = f["sub_label"]
        output["sections"][sec].append(entry)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)

    print(f"\n\n{'═'*65}")
    print("  SUMMARY")
    print("═" * 65)
    print(f"   Owner  : {owner_name or 'N/A'}")
    print(f"   Locked : {is_locked}")
    for sec, fields in output["sections"].items():
        print(f"\n  [{sec}]")
        for f in fields:
            sub = f" ({f['sub_label']})" if f.get("sub_label") else ""
            print(f"    {f['label']:25s} → {f['value']}{sub}")
    print(f"\n  Saved to {OUTPUT_FILE}")
    return output


if __name__ == "__main__":
    main()
