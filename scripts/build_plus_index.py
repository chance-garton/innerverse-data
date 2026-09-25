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

2026-09-25: each entry is also ENRICHED from the files the two Airtable
builders wrote earlier in the same run (episodes/<slug>.json and
episodes-index.json), read from disk, never from Airtable: freeSlug (the
row's Slug, so the /plus archive can join the members' post to its free
side by slug instead of by title), topicLine, plusDuration, guests, topics
and tags. Every field is optional and the enrichment is skipped, entry by
entry, when a file is missing, so this script still needs no token and
still cannot fail on the free side's account.
"""

import html
import json
import os
import sys
import time
import urllib.error
import urllib.request

def clean_image_url(u):
    """Strip the query off a Squarespace image URL.

    The CDN only honours format= as the FIRST query parameter, so a stored
    URL like ...png?content-type=image%2Fpng defeats every attempt to resize
    it later and the full size file is served instead. The site always
    appends its own format=, so the clean base URL is what belongs in the
    index files. See claude/iv-home.md in the Website Recode project.
    """
    u = (u or "").strip()
    if "images.squarespace-cdn.com" in u and "?" in u:
        return u.split("?", 1)[0]
    return u


SITE = "https://www.innerversepodcast.com"
COLLECTION = "/plus?format=json&nojs=true"
OUT_PATH = "plus-index.json"

# Where the enrichment comes from: the per-episode files (one per Slug and
# one per Plus Slug, so a members' slug resolves directly) and the free
# index (for the Squarespace tags on the free post). Both are written
# earlier in the same workflow run; if either is absent the entries simply
# go out without those fields, as they did before 2026-09-25.
EPISODES_DIR = "episodes"
FREE_INDEX_PATH = "episodes-index.json"
HOST_NAME = "Chance Garton"

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
# 2026-09-11: dylan-saccoccio-norse-phoenicians-te78l (Phoenician Origins
# of Norse Mythology) was checked against the same list and had no
# matching free page - Chance resolved it directly by moving the post
# itself from /plus to /episodes under the SAME slug, so no slug-mismatch
# redirect logic is needed here; it just falls out of live_slugs like any
# other episode once it disappeared from /plus.
#
# 2026-09-11: jan-ott-dylan-saccoccio-oera-linda-book is the reverse case -
# a free /episodes post that never had a /plus page at all, but covers the
# same Oera Linda material as the two entries above, so it belongs in
# /plus search for member discoverability too. Categories are approximated
# to match the /plus taxonomy (the /episodes collection uses a different,
# incompatible category set) using the same Show/Theme as its sibling
# Oera Linda entries above.
#
# 2026-09-11: astroherbalism-gemini, astroherbalism-cancer and
# leo-astroherbalism are the same reverse case as jan-ott-dylan-saccoccio
# above, applied to the Astro-Herbalism remaster series - they're free
# /episodes posts that never had a /plus page, but Chance wants them
# surfaced in /plus browsing so premium members notice them. Same pattern
# applies to every future Astro-Herbalism remake: add it here too, using
# its Airtable Show Categories ("Astro-Herbalism", "Vibe Rant") and Themes
# ("Holistic Health" / "Myth-Symbolism-Language" etc, renamed to match the
# /plus taxonomy's hyphenated theme names) and its own publish date.
REDIRECTS = {
        # 2026-09-18: robert-comber-lost-octave is the reverse case again - a
    # free /episodes post with no /plus page. The guest objected to the
    # second half being paywalled, so the FULL 2h20m version was published
    # free everywhere (YouTube and Acast both carry it). Chance still wants
    # it in the members' feed, and the free-item path picks up the row's
    # Acast Audio URL, which is already the full cut.
    "robert-comber-lost-octave": {
        "title": "Robert Comber | The Lost Octave of the I Ching: Star Lore, Number, & The Cosmic Language Pattern",
        "url": SITE + "/episodes/robert-comber-lost-octave",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1713195924164-7B0L6DSJJZ0KQV973ZLN/IMG_4732.JPG",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality", "Myth-Symbolism-Language"],
        "date": "2024-04-15",
    },
    # 2026-09-18: clive-de-carle-nutritional-gnosis and elise-frosch are the
    # same case as robert-comber-lost-octave above - free /episodes posts
    # that were given away in full, so there is no members-only cut and no
    # /plus page to build. Chance wants both surfaced in /plus browsing and
    # in the members' feed, and the free-item path picks up each row's
    # Acast Audio URL, which is already the full show.
    "clive-de-carle-nutritional-gnosis": {
        "title": "Clive De Carle | Effective Nutritional Gnosis: Supplements, Health Technology & the Magic Chair",
        "url": SITE + "/episodes/clive-de-carle-nutritional-gnosis",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1735662645314-598PS88WFXPXLQOPDT05/IMG_6786.JPG",
        "shows": ["Innerverse"],
        "themes": ["Holistic Health"],
        "date": "2024-12-31",
    },
    "elise-frosch": {
        "title": "Elise Frosch | Preparing For Childbearing: Advice and Techniques For Ecstatic Natural Birth",
        "url": SITE + "/episodes/elise-frosch",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1720536260358-J27KNL8VLM7L0WOENXMV/IMG_5280.JPG",
        "shows": ["Innerverse"],
        "themes": ["Holistic Health"],
        "date": "2024-07-09",
    },
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
    "dylan-saccoccio-norse-phoenicians-te78l": {
        "title": "Phoenician Origins of Norse Mythology: Dylan Saccoccio on the Trail of the Holy Sailors",
        "url": SITE + "/episodes/dylan-saccoccio-norse-phoenicians-te78l",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1779280397625-U6L03NZQ6NF1L06HZG7P/Phoenician+Origins+of+Norse+Mythology+Dylan+Saccoccio+on+the+Trail+of+the+Holy+Sailors.png",
        "shows": ["Inner Whirled", "Innerverse"],
        "themes": ["Myth-Symbolism-Language", "Alternative History"],
        "date": "2023-04-16",
    },
    "astroherbalism-gemini": {
        "title": "Gemini Astro-Herbalism: Mercury, The Air Element, & Herbal Signatures",
        "url": SITE + "/episodes/astroherbalism-gemini",
        "thumb": "https://images.squarespace-cdn.com/content/5987d897cf81e0278ec5322e/1780664773490-213VV4VPZJFH1B8N68QI/Gemini+Herbs+Mercury%2C+Cedar%2C+Holy+Basil+%26+The+Mint+Mystery++Astro-Herbalism.png",
        "shows": ["Astro-Herbalism", "Vibe Rant"],
        "themes": ["Holistic Health", "Myth-Symbolism-Language"],
        "date": "2026-06-05",
    },
    "astroherbalism-cancer": {
        "title": "Cancer Astro-Herbalism: Linden, Willow, Marshmallow & Aloe",
        "url": SITE + "/episodes/astroherbalism-cancer",
        "thumb": "https://images.squarespace-cdn.com/content/5987d897cf81e0278ec5322e/1788905125293-1HCB4AP9SAO2UQETQKR0/Cancer+Season+Herbs+Linden%2C+Willow%2C+Marshmallow%2C+Aloe++Astro+Herbalism.jpg",
        "shows": ["Astro-Herbalism", "Vibe Rant"],
        "themes": ["Holistic Health", "Myth-Symbolism-Language"],
        "date": "2026-06-17",
    },
    "leo-astroherbalism": {
        "title": "St John's Wort, Motherwort & Hawthorn: Leo Season Herbs",
        "url": SITE + "/episodes/leo-astroherbalism",
        "thumb": "https://images.squarespace-cdn.com/content/5987d897cf81e0278ec5322e/1786888416132-9H0MKV4JJKDLQ2D2TH11/ASTROHERBALISM+VIBE+RANT+LEO+INNERVERSE.png",
        "shows": ["Astro-Herbalism", "Vibe Rant"],
        "themes": ["Holistic Health", "Myth-Symbolism-Language"],
        "date": "2026-08-16",
    },
    "astroherbalism-virgo": {
        "title": "Virgo Season Herbs: Gentle Plant Medicine for Digestion, Nerves & Calm",
        "url": SITE + "/episodes/astroherbalism-virgo",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1789568552495-0SKTMKOZUX0D3HJKVL4I/ASTROHERBALISM+VIRGO+INNERVERSE.png",
        "shows": ["Astro-Herbalism", "Vibe Rant"],
        "themes": ["Holistic Health", "Myth-Symbolism-Language"],
        "date": "2026-09-16",
    },
    # 2026-09-13: call-of-the-old-gods deleted from /plus (Chance confirmed:
    # the full 2-hour recording was released for free, so the Plus cut is
    # entirely redundant - the free episode's own Duration is 1h 59m, an
    # exact match for what had been the Plus-only runtime). Free page lives
    # under a different slug, same pattern as crrow777-revelation above.
    "call-of-the-old-gods": {
        "title": "The Call of the Old Gods: Paganism & the Cosmic Archetypal Psyche | Dr. Christopher McIntosh",
        "url": SITE + "/episodes/christopher-mcintosh-call-of-the-old-gods",
        "thumb": "https://images.squarespace-cdn.com/content/5987d897cf81e0278ec5322e/1750350587770-492O095QJUIBUJCIPG3C/mcintosh-sq-thumb.jpg?content-type=image%2Fjpeg",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language", "Consciousness And Reality"],
        "date": "2025-06-19",
    },
    # 2026-09-18: kurtis-r-kallenbach-placenta is another free-in-full case.
    # It went out as a Vibe Rant and never got a members-only cut, so there
    # is no Vimeo upload and no /plus page to build. Chance wants it in
    # /plus browsing and in the members' feed off the row's Acast Audio URL,
    # which is the full 3h 2m show.
    "kurtis-r-kallenbach-placenta": {
        "title": "Your Birth Certificate Belongs to a Dead Person: The Placenta Mystery | Kurtis R. Kallenbach",
        "url": SITE + "/episodes/kurtis-r-kallenbach-placenta",
        "thumb": "https://images.squarespace-cdn.com/content/v1/5987d897cf81e0278ec5322e/1780603254560-BAGCUSRQ2QROPM3A17CH/Your+Birth+Certificate+Belongs+to+a+Dead+Person+The+Placenta+Mystery++Kurtis+R.+Kallenbach.png",
        "shows": ["Innerverse", "Vibe Rant"],
        "themes": ["Holistic Health", "Alternative History"],
        "date": "2023-05-10",
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
                "thumb": clean_image_url(it.get("assetUrl")),
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

    for e in out:
        e["thumb"] = clean_image_url(e.get("thumb"))

    out.sort(key=lambda e: (e["date"] or ""), reverse=True)
    return out


def free_slug_of(entry):
    """The free page's slug for an entry: the /episodes/<slug> in a
    REDIRECTS url, else the entry's own slug (free and Plus share it on
    every normally deployed row)."""
    url = entry.get("url") or ""
    marker = "/episodes/"
    if marker in url:
        return url.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
    return entry["slug"]


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def enrich(posts):
    """Add freeSlug, topicLine, plusDuration, guests, topics and tags from
    the files the Airtable builders wrote earlier in this run. Read-only,
    best effort, one entry at a time."""
    free_index = read_json(FREE_INDEX_PATH) or {}
    free_by_slug = {e.get("slug"): e for e in free_index.get("episodes") or [] if e.get("slug")}
    hit = 0
    for e in posts:
        candidates = [e["slug"], free_slug_of(e)]
        ep = None
        for c in candidates:
            ep = read_json(os.path.join(EPISODES_DIR, c + ".json"))
            if ep:
                break
        if not ep:
            continue
        f = ep.get("fields") or {}
        free_slug = f.get("Slug") or free_slug_of(e)
        e["freeSlug"] = free_slug
        if f.get("Topic Line"):
            e["topicLine"] = f["Topic Line"]
        if f.get("Plus Duration"):
            e["plusDuration"] = f["Plus Duration"]
        if f.get("Topics"):
            e["topics"] = list(f["Topics"])
        guests = [g.get("Name") for g in (ep.get("_guestsById") or {}).values() if g.get("Name")]
        guests = [g for g in guests if g != HOST_NAME]
        if guests:
            e["guests"] = guests
        free = free_by_slug.get(free_slug)
        if free and free.get("tags"):
            e["tags"] = list(free["tags"])
        hit += 1
    return hit


def main():
    print("Fetching the /plus collection ...")
    posts = plus_posts()
    print(f"  {len(posts)} posts")

    # A partial fetch must never overwrite a good index with a short one.
    # (REDIRECTS entries count toward this floor too, which is fine - the
    # live fetch still has to clear ~40 on its own for this to pass.)
    if len(posts) < 40:
        sys.exit("ERROR: /plus returned suspiciously few posts; refusing to write.")

    enriched = enrich(posts)
    print(f"  {enriched} of {len(posts)} entries enriched from {EPISODES_DIR}/ and {FREE_INDEX_PATH}")

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
