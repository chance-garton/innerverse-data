#!/usr/bin/env python3
"""
Build episodes-index.json for the InnerVerse /episodes search widget.

Sources:
  1. Airtable "InnerVerse Episodes" base  -> episode metadata
  2. The live Squarespace collection JSON -> canonical URL + thumbnail,
     and proof the episode actually has a live public page

Only episodes that exist in BOTH are written out, so the widget can never
link to a page that is not there.

Airtable fields are addressed by FIELD ID, not by name, on purpose: a field
rename in the Airtable UI silently breaks name-based access (this has
already happened once on this base, when "YouTube URL" became "Video URL").
Field IDs never change.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN", "").strip()
if not AIRTABLE_TOKEN:
    sys.exit("ERROR: AIRTABLE_TOKEN is not set. Add it as a repository secret.")

BASE_ID = "appg1ujebSIw7TyFW"
EPISODES_TABLE = "tbl8lZF3m1yZZ1hcQ"
GUESTS_TABLE = "tblq0USTWxfIEYiKV"

SITE = "https://www.innerversepodcast.com"
COLLECTION = "/episodes?format=json&nojs=true"

MIN_YEAR = 2020

# Two files on purpose. The slim index is what the page fetches on load and
# is roughly a tenth the size; the transcript-derived text is much larger and
# is fetched lazily just after first paint, widening the same search once it
# lands. Keeping them separate is what makes the page feel instant.
OUT_PATH = "episodes-index.json"
EXTRA_PATH = "episodes-extra.json"

# --- Airtable field IDs (stable across renames) -------------------------
F_SLUG = "fld9pDFBRiZYNl8IR"
F_TITLE = "fldGbtuFLmXQhpRj3"
F_SHOWS = "fld9Ljoj6WcnhudCr"   # Show Categories
F_TOPICS = "fldLgLKhc4XWca00E"  # Topics
F_YEAR = "fld37NaLPgm1rnnHN"
F_DATE = "fldriTOlSEOUxDdYe"    # Publish Date
F_DURATION = "fld6Zajp8Ami13S6V"
F_THUMB = "fldgbAlgTpwOj6V63"   # Thumbnail URL
F_GUESTS = "fldhrTolEQpztEBCL"  # linked -> Guests
F_CHAPTERS = "fldHc4xyaABvEJuf5"
F_QUOTES = "fld0YCssGV4dgqtkg"
F_THEMES = "fldZ3ERjnHPk4aZpO"

F_GUEST_NAME = "fld5YGyyN9zmfXdz4"


def get_json(url, headers=None, tries=7):
    """GET with retry/backoff.

    Two different rate limits apply here. Airtable allows 5 req/sec per
    base. Squarespace throttles the collection JSON too, and it returns a
    429 with an HTML body rather than JSON, which is why the backoff is
    generous: a daily job can afford to wait rather than fail.
    """
    for attempt in range(tries):
        req = urllib.request.Request(
            url, headers={"User-Agent": "innerverse-index-builder", **(headers or {})}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                # Honour Retry-After when the server sends one.
                wait = 0
                try:
                    wait = int(e.headers.get("Retry-After") or 0)
                except Exception:
                    wait = 0
                time.sleep(max(wait, min(60, 3 * (2 ** attempt))))
                continue
            body = ""
            try:
                body = e.read().decode()[:400]
            except Exception:
                pass
            raise SystemExit(f"ERROR: {e.code} fetching {url.split('?')[0]} :: {body}")
        except Exception:
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise SystemExit("ERROR: exhausted retries")


def airtable_all(table):
    """Page through a whole table, returning fields keyed by field ID."""
    out = []
    offset = None
    headers = {"Authorization": "Bearer " + AIRTABLE_TOKEN}
    while True:
        params = {"pageSize": "100", "returnFieldsByFieldId": "true"}
        if offset:
            params["offset"] = offset
        url = (f"https://api.airtable.com/v0/{BASE_ID}/{table}"
               f"?{urllib.parse.urlencode(params)}")
        data = get_json(url, headers)
        out.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            return out
        time.sleep(0.25)  # stay well under the rate limit


def site_index():
    """Slug -> {url, thumb, title} for every live post on /episodes."""
    out = {}
    seen = set()
    url = COLLECTION
    pages = 0
    while url and pages < 60:
        data = get_json(SITE + url)
        for it in data.get("items", []):
            if it.get("id") in seen:
                continue
            seen.add(it["id"])
            slug = it.get("urlId")
            if not slug:
                continue
            out[slug] = {
                "url": SITE + (it.get("fullUrl") or "/episodes/" + slug),
                "thumb": it.get("assetUrl") or "",
                "title": it.get("title") or "",
            }
        pages += 1
        pg = data.get("pagination") or {}
        nxt = pg.get("nextPageUrl")
        if not (pg.get("nextPage") and nxt):
            break
        url = nxt + ("&" if "?" in nxt else "?") + "format=json&nojs=true"
        # Be a polite guest. This is 17-ish sequential pages against a site
        # that will start returning 429s if hit hard, and this job runs once
        # a day, so a second between pages costs nothing that matters.
        time.sleep(1.0)
    return out


def names_from(val):
    if not val:
        return []
    if isinstance(val, list):
        return [v for v in val if isinstance(v, str)]
    return []


def searchable_extra(fields):
    """Flatten Chapters/Quotes/Themes JSON into plain text where present.

    As the transcript work fills these in, they simply start appearing here
    and the widget's search gets deeper with no code change.
    """
    bits = []
    for fid in (F_CHAPTERS, F_QUOTES, F_THEMES):
        raw = fields.get(fid)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            bits.append(str(raw))
            continue
        for entry in (parsed if isinstance(parsed, list) else []):
            if isinstance(entry, dict):
                for k in ("title", "text", "body", "author"):
                    if entry.get(k):
                        bits.append(str(entry[k]))
            elif isinstance(entry, str):
                bits.append(entry)
    return " ".join(bits).strip()


def main():
    print("Fetching Airtable guests ...")
    guest_name = {}
    for rec in airtable_all(GUESTS_TABLE):
        nm = (rec.get("fields") or {}).get(F_GUEST_NAME)
        if nm:
            guest_name[rec["id"]] = nm
    print(f"  {len(guest_name)} guests")

    print("Fetching Airtable episodes ...")
    episodes = airtable_all(EPISODES_TABLE)
    print(f"  {len(episodes)} rows")

    print("Fetching live site collection ...")
    live = site_index()
    print(f"  {len(live)} live posts")
    if len(live) < 50:
        sys.exit("ERROR: live collection returned suspiciously few posts; refusing to write.")

    out = []
    skipped_year = skipped_nolive = skipped_noslug = 0

    for rec in episodes:
        f = rec.get("fields") or {}
        slug = f.get(F_SLUG)
        if not slug:
            skipped_noslug += 1
            continue

        try:
            year = int(str(f.get(F_YEAR) or "")[:4])
        except Exception:
            year = None
        if year is None or year < MIN_YEAR:
            skipped_year += 1
            continue

        lv = live.get(slug)
        if not lv:
            skipped_nolive += 1
            continue

        guests = [guest_name[g] for g in (f.get(F_GUESTS) or [])
                  if isinstance(g, str) and g in guest_name]

        out.append({
            "slug": slug,
            "title": f.get(F_TITLE) or lv["title"],
            "url": lv["url"],
            "thumb": f.get(F_THUMB) or lv["thumb"],
            "topics": names_from(f.get(F_TOPICS)),
            "shows": names_from(f.get(F_SHOWS)),
            "guests": guests,
            "date": f.get(F_DATE) or "",
            "duration": f.get(F_DURATION) or "",
            "extra": searchable_extra(f),
        })

    out.sort(key=lambda e: (e["date"] or ""), reverse=True)

    if not out:
        sys.exit("ERROR: built an empty index; refusing to overwrite the live file.")

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Deep text goes into its own file, keyed by slug.
    extra = {e["slug"]: e["extra"] for e in out if e["extra"]}
    slim = [{k: v for k, v in e.items() if k != "extra"} for e in out]

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump({"generated": stamp, "count": len(slim), "episodes": slim},
                  fh, ensure_ascii=False, separators=(",", ":"))

    with open(EXTRA_PATH, "w", encoding="utf-8") as fh:
        json.dump({"generated": stamp, "count": len(extra), "extra": extra},
                  fh, ensure_ascii=False, separators=(",", ":"))

    print(f"\nWrote {OUT_PATH}:  {len(slim)} episodes, "
          f"{os.path.getsize(OUT_PATH) / 1024:.0f} KB")
    print(f"Wrote {EXTRA_PATH}: {len(extra)} episodes with deep text, "
          f"{os.path.getsize(EXTRA_PATH) / 1024:.0f} KB")
    print(f"  skipped: {skipped_year} pre-{MIN_YEAR}, "
          f"{skipped_nolive} with no live page, {skipped_noslug} with no slug")


if __name__ == "__main__":
    main()
