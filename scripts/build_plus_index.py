#!/usr/bin/env python3
"""
Build plus-index.json: every live post in the members' /plus collection.

Sourced entirely from the live Squarespace collection, NOT from Airtable,
deliberately. As of 2026-09 Airtable holds only 57 of the 108 /plus posts,
so an Airtable-sourced filter would silently hide half the members'
catalogue. Every /plus post, by contrast, already carries complete
categories, which is all the Show/Theme filter needs.

Post bodies are never read. They are paywalled, and for a signed-in member
the collection listing balloons to ~250 KB per page (~1.5 MB for the lot),
which is exactly why the browser cannot build this index for itself.

Runs alongside build_index.py in the same daily workflow. Kept separate so a
failure here can never take the free /episodes index down with it.
"""

import html
import json
import os
import sys
import time
import urllib.error
import urllib.request

SITE = "https://www.innerversepodcast.com"
COLLECTION = "/plus?format=json&nojs=true"
OUT_PATH = "plus-index.json"

# Categories that name a SHOW rather than a theme, lower-cased for matching.
# Anything else a post carries is treated as a theme, so a NEW THEME needs no
# code change while a NEW SHOW must be added here or it will render as a theme.
SHOWS = {
    "innerverse",
    "inner whirled",
    "vibe rant",
    "astro-herbalism",
    "marvelous demystifiers",
    "chance guest spots",
    "innerverse plus+",
}

# "Redundant" /plus entries: free-only episodes that had a /plus page for
# discoverability but no distinct Plus cut, and whose /plus page has since
# been deleted (moved to Squarespace Trash). Once the post is gone it drops
# out of the live Squarespace /plus collection entirely, so without this
# list it would silently vanish from /plus search instead of still being
# findable. Add one entry here every time a page like this is deleted, so
# the episode stays discoverable in /plus search and points at the real,
# free-only page instead of a dead /plus URL.
#
# 2026-09-11: crrow777-revelation deleted from /plus (Chance confirmed:
# Trash, recoverable, not a permanent purge). Its free page lives under a
# DIFFERENT slug than the /plus one did (crrow-777-revelation, with a
# hyphen splitting "crrow" and "777" - a genuine slug mismatch between the
# two collections, not a typo here).
#
# 2026-09-11: three more of the same situation, all confirmed by matching
# the underlying YouTube video ID between the /plus post and the /episodes
# post (title similarity alone is not reliable here - see the
# dylan-saccoccio-holy-sailors near-miss noted in the recipe doc):
#   - royal-stars -> /episodes/royal-stars (slugs match, simple case)
#   - oera-linda-manuscript-a454d -> /episodes/oera-linda-manuscript
#     (the /plus title is literally tagged "(Copy)" - a duplicate post)
#   - oera-linda-book-examined -> /episodes/oera-linda-book
#
# dylan-saccoccio-norse-phoenicians-te78l (Phoenician Origins of Norse
# Mythology) was checked against the same list and has NO matching free
# page - it is a distinct, real Plus episode (own Vimeo ID) and is
# deliberately left OUT of this list. Do not add it without Chance
# confirming what it should point to.
#
# 2026-09-11: jan-ott-dylan-saccoccio-oera-linda-book is the reverse case -
# a free /episodes post that never had a /plus page at all, but covers the
# same Oera Linda material as the two entries above, so it belongs in
# /plus search for member discoverability too. Categories are approximated
# to match the /plus taxonomy (the /episodes collection uses a different,
# incompatible category set) using the same Show/Theme as its sibling
# Oera Linda entries above.
REDIRECTS = {
    "crrow777-revelation": {
        "title": "Was the Book of Revelation Rewritten? Crrow777 w/ Chance Garton",
        "url": SITE + "/episodes/crrow-777-revelation",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1784137886568-KVUH2MF5UQ9EOCTO04HV/crrow777-1st.jpg",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language", "Alternative History"],
        "date": "2026-07-15",
    },
    "royal-stars": {
        "title": "The Four Evangelists, Four Horsemen and the Sphinx Encode The Royal Stars",
        "url": SITE + "/episodes/royal-stars",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1779228340119-8RHVQV7VW51ZUQTVZ5IK/Dylan+Saccoccio+The+Four+Evangelists+Are+the+Four+Royal+Stars%2C+and+so+are+the+Four+Horsemen.png",
        "shows": ["Inner Whirled", "Innerverse"],
        "themes": ["Myth-Symbolism-Language"],
        "date": "2021-05-06",
    },
    "oera-linda-manuscript-a454d": {
        "title": "The Oera Linda Book Part 2: Allegory, the Holy Sailors and the Astro-Theology Beneath the Manuscript",
        "url": SITE + "/episodes/oera-linda-manuscript",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1779377198021-KZ56ZY5JAPOHX4LGUU8B/The+Oera+Linda+Book+Part+2+Allegory%2C+the+Holy+Sailors+and+the+Astro-Theology+Beneath+the+Manuscript.png",
        "shows": ["Inner Whirled"],
        "themes": ["Myth-Symbolism-Language", "Alternative History"],
        "date": "2023-09-20",
    },
    "oera-linda-book-examined": {
        "title": "The Oera Linda Book: A Forbidden Frisian Manuscript Examined With Dylan Saccoccio & Slick Dissident",
        "url": SITE + "/episodes/oera-linda-book",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1779375486345-LLC3580FFP3NDVZ5KLIS/The+Oera+Linda+Book+A+Forbidden+Frisian+Manuscript+Examined+With+Dylan+Saccoccio.png",
        "shows": ["Inner Whirled"],
        "themes": ["Myth-Symbolism-Language", "Alternative History"],
        "date": "2023-08-23",
    },
    "jan-ott-dylan-saccoccio-oera-linda-book": {
        "title": "Jan Ott & Dylan Saccoccio | The Oera Linda Book: Linguistic Artifacts of Post-Flood Hidden History",
        "url": SITE + "/episodes/jan-ott-dylan-saccoccio-oera-linda-book",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1693163099558-82ULR2PTSKI9BUBCLV0L/IMG_2871.JPG",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language", "Alternative History"],
        "date": "2023-08-28",
    },
}


def get_json(url, tries=7):
    """GET with retry/backoff. Squarespace rate-limits the collection JSON."""
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": "innerverse-index-builder"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                try:
                    wait = int(e.headers.get("Retry-After") or 0)
                except Exception:
                    wait = 0
                time.sleep(max(wait, min(60, 3 * (2 ** attempt))))
                continue
            raise SystemExit(f"ERROR: {e.code} fetching {url.split('?')[0]}")
        except Exception:
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise SystemExit("ERROR: exhausted retries")


def plus_posts():
    out, seen = [], set()
    url, pages = COLLECTION, 0
    while url and pages < 40:
        data = get_json(SITE + url)
        for it in data.get("items", []):
            if it.get("id") in seen:
                continue
            seen.add(it.get("id"))
            slug = it.get("urlId")
            if not slug:
                continue
            cats = [c for c in (it.get("categories") or []) if isinstance(c, str)]
            stamp = it.get("publishOn")
            date = time.strftime("%Y-%m-%d", time.gmtime(stamp / 1000)) if isinstance(stamp, int) else ""
            out.append({
                "slug": slug,
                # Squarespace returns titles HTML-escaped: "Marty Leeds &amp; ..."
                "title": html.unescape(it.get("title") or ""),
                "url": SITE + (it.get("fullUrl") or "/plus/" + slug),
                "thumb": it.get("assetUrl") or "",
                "shows": [c for c in cats if c.strip().lower() in SHOWS],
                "themes": [c for c in cats if c.strip().lower() not in SHOWS],
                "date": date,
            })
        pages += 1
        pg = data.get("pagination") or {}
        nxt = pg.get("nextPageUrl")
        if not (pg.get("nextPage") and nxt):
            break
        url = nxt + ("&" if "?" in nxt else "?") + "format=json&nojs=true"
        time.sleep(1.0)

    # Merge in the redirect entries for deleted-but-still-findable episodes.
    # Guarded so a slug that's somehow live again on Squarespace is never
    # double-listed - the real post always wins.
    live_slugs = {p["slug"] for p in out}
    for slug, entry in REDIRECTS.items():
        if slug not in live_slugs:
            out.append({"slug": slug, **entry})

    out.sort(key=lambda e: (e["date"] or ""), reverse=True)
    return out


def main():
    print("Fetching the /plus collection ...")
    posts = plus_posts()
    print(f"  {len(posts)} posts")

    # A partial fetch must never overwrite a good index with a short one.
    # (REDIRECTS entries count toward this floor too, which is fine - the
    # live fetch still has to clear ~40 on its own for this to pass.)
    if len(posts) < 40:
        sys.exit("ERROR: /plus returned suspiciously few posts; refusing to write.")

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump({"generated": stamp, "count": len(posts), "episodes": posts},
                  fh, ensure_ascii=False, separators=(",", ":"))

    no_show = [p["slug"] for p in posts if not p["shows"]]
    no_theme = [p["slug"] for p in posts if not p["themes"]]
    print(f"Wrote {OUT_PATH}: {len(posts)} posts, {os.path.getsize(OUT_PATH) / 1024:.0f} KB")
    if no_show:
        print(f"  NOTE: {len(no_show)} post(s) carry no show category: {', '.join(no_show[:5])}")
    if no_theme:
        print(f"  NOTE: {len(no_theme)} post(s) carry no theme category: {', '.join(no_theme[:5])}")


if __name__ == "__main__":
    main()

