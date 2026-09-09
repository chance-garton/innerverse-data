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
    out.sort(key=lambda e: (e["date"] or ""), reverse=True)
    return out


def main():
    print("Fetching the /plus collection ...")
    posts = plus_posts()
    print(f"  {len(posts)} posts")

    # A partial fetch must never overwrite a good index with a short one.
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
