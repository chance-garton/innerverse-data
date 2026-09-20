#!/usr/bin/env python3
"""
Build one static JSON file per episode for the InnerVerse episode pages.

WHY THIS EXISTS
Every /episodes/<slug> and /plus/<slug> page used to call api.airtable.com
directly from the browser, which meant a readable Airtable token sat in the
public page source of every episode page and Airtable was a runtime
dependency of the website. These files replace that call: the render script
fetches its own episode's file from the GitHub CDN and reads exactly the
shape the Airtable REST response used to hand it.

THE SHAPE IS THE CONTRACT
Each file is {"generated": ..., "fields": {...}} where "fields" is keyed by
Airtable FIELD NAME, because that is what the render script reads
(r['Title'], r['Plus Chapters JSON'] and so on). Linked Guests and
Affiliates keep their record-id arrays, so linkedIds() still works, and the
records themselves are expanded inline under _guestsById / _affiliatesById
so the two follow-up requests the page used to make are gone as well.

Airtable is read by FIELD ID here, never by name, so a rename in the
Airtable UI cannot silently empty the site again the way "YouTube URL" to
"Video URL" once did. The field NAME appears only as the output key.

NOTHING NON-PUBLIC MAY GO IN THESE FILES. The repo is public. Every field
below is already rendered on the public page. Plus RSS Description and the
Feed Share Alerts table are deliberately absent and must stay absent.
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
AFFILIATES_TABLE = "tblKjOK5bMcCEpk1p"

OUT_DIR = "episodes"

# The host's Guests row. The render script appends it to every episode's
# guest list whether or not the episode links him, so every file has to
# carry it or his panel would vanish from the sidebar.
HOST_GUEST_ID = "rec7Vm5QNrDbc9sdb"

# A partial Airtable pull must never overwrite a good set of files.
MIN_ROWS = 500

# --- Episodes: field id -> the NAME the render script reads --------------
EP_FIELDS = {
    "fld9pDFBRiZYNl8IR": "Slug",
    "fld57jYOGzqGjkTA4": "Plus Slug",
    "fldGbtuFLmXQhpRj3": "Title",
    "fldmfWSeYuTN2pp3W": "Topic Line",
    "fld37NaLPgm1rnnHN": "Year",
    "fldcmDz1y2jJaMPj3": "Episode Number",
    "fldriTOlSEOUxDdYe": "Publish Date",
    "fld6Zajp8Ami13S6V": "Duration",
    "fldgbAlgTpwOj6V63": "Thumbnail URL",
    "fldf3R6oRcg1Osqfc": "Video URL",
    "fldu9RHRJKNe2U0L8": "YouTube Plus URL",
    "fldxQM1lxVLEkrLcX": "Acast Audio URL",
    "fldJhnp39p4pDGAL7": "Intro Paragraph 1",
    "fldOlThhvIN7HdJu6": "Intro Paragraph 2",
    "fldHc4xyaABvEJuf5": "Chapters JSON",
    "fld0YCssGV4dgqtkg": "Quotes JSON",
    "fldZ3ERjnHPk4aZpO": "Core Themes JSON",
    "fldhrTolEQpztEBCL": "Guests",
    "fldnohYr6kGzp7gct": "Affiliates Shown",
    "fldfqDfoGXo63By2V": "Direct Plus URL",
    "fldNZhOUOaTkVpaCo": "Substack Post URL",
    "fldn69kLQvKdXOHDt": "Patreon Post URL",
    "fldLgLKhc4XWca00E": "Topics",
    "fld9Ljoj6WcnhudCr": "Show Categories",
    "fldTZzCqTSk8Ou8XK": "Use New Template",
    "fldc2niCZSekUFcmF": "Plus Video URL",
    "fldAj47ivVr6VCRmr": "Plus Audio URL",
    "fld5zjdCUxURJ5EY6": "Plus Chapters JSON",
    "fldbgqkJUyuL8Xewr": "Plus Quotes JSON",
    "fldFQrou1GZ8E0xkM": "Plus Core Themes JSON",
    "fldKP65RFUUYjrERr": "Plus Free Chapters JSON",
    "fldimHDwCSXcFrTuQ": "Plus Duration",
}

# Fields the related-episodes corpus needs, and only those. It is fetched
# once per page by every episode page, so it stays lean.
CORPUS_FIELDS = [
    "Slug", "Title", "Topic Line", "Topics", "Show Categories",
    "Guests", "Publish Date", "Thumbnail URL", "Episode Number",
]

GUEST_FIELDS = {
    "fld5YGyyN9zmfXdz4": "Name",
    "fldlRkbdm2wB1rVi1": "Portrait URL",
    "fldmJAOIap6Gu1JgB": "Role",
    "fldvVJ3cjh2eBsxOV": "Bio",
    "fldJmLAUBKtlZb7xf": "Guest Page Slug",
    "fld9qymF5bOmSHKUX": "Website URL",
    "fldYliVervqJTtrFi": "YouTube URL",
    "fldpUH5w9bNNl6G7d": "Substack URL",
    "fldQXgUtzTVomPu20": "Books URL",
    "fldoVYbHAkRvJgMJo": "Socials URL",
}

AFF_FIELDS = {
    "fldmOsIa4xjTHm2rB": "Name",
    "fldcx6vT74BHB8sio": "Body",
    "fldfAroti6l3dHhTK": "Offer Line",
    "fldPs35FO978Fmvs8": "Primary Link Label",
    "flddrhSA94GGIVTwG": "Primary Link URL",
    "fldWXJJwwOivI6DKD": "Secondary Link Label",
    "flddd3e91WdyRCoRt": "Secondary Link URL",
    "fld37FUagI2hvwiP5": "Note",
    "fld39o3OceuR4nzim": "Books JSON",
}


def get_json(url, headers=None, tries=7):
    for attempt in range(tries):
        req = urllib.request.Request(
            url, headers={"User-Agent": "innerverse-index-builder", **(headers or {})}
        )
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
        time.sleep(0.25)


def rename(fields, mapping):
    """field-id keyed -> field-name keyed, dropping blanks and anything
    not on the allow list above."""
    out = {}
    for fid, name in mapping.items():
        v = fields.get(fid)
        if v is None or v == "" or v == []:
            continue
        out[name] = v
    return out


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"),
                  sort_keys=True)


def main():
    print("Fetching Airtable guests ...")
    guests = {r["id"]: rename(r.get("fields") or {}, GUEST_FIELDS)
              for r in airtable_all(GUESTS_TABLE)}
    print(f"  {len(guests)} guests")

    print("Fetching Airtable affiliates ...")
    affiliates = {r["id"]: rename(r.get("fields") or {}, AFF_FIELDS)
                  for r in airtable_all(AFFILIATES_TABLE)}
    print(f"  {len(affiliates)} affiliates")

    print("Fetching Airtable episodes ...")
    rows = airtable_all(EPISODES_TABLE)
    print(f"  {len(rows)} rows")
    if len(rows) < MIN_ROWS:
        sys.exit(f"ERROR: only {len(rows)} episode rows returned (expected at "
                 f"least {MIN_ROWS}); refusing to overwrite the live files.")

    if HOST_GUEST_ID not in guests:
        sys.exit("ERROR: the host's Guests row is missing; every episode file "
                 "needs it. Refusing to write.")

    os.makedirs(OUT_DIR, exist_ok=True)

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    written = {}
    corpus = []
    newest_plus = None
    collisions = []

    for rec in rows:
        raw = rec.get("fields") or {}
        f = rename(raw, EP_FIELDS)
        slug = f.get("Slug")
        if not slug:
            continue

        corpus.append({
            "id": rec["id"],
            "fields": {k: v for k, v in f.items() if k in CORPUS_FIELDS},
        })

        gids = [g for g in (f.get("Guests") or []) if isinstance(g, str)]
        if HOST_GUEST_ID not in gids:
            gids = gids + [HOST_GUEST_ID]
        aids = [a for a in (f.get("Affiliates Shown") or []) if isinstance(a, str)]

        payload = {
            "generated": stamp,
            "recordId": rec["id"],
            "fields": f,
            "_guestsById": {g: guests[g] for g in gids if g in guests},
            "_affiliatesById": {a: affiliates[a] for a in aids if a in affiliates},
        }

        names = [slug]
        plus_slug = f.get("Plus Slug")
        if plus_slug and plus_slug != slug:
            names.append(plus_slug)

        for name in names:
            if name in written and written[name] != rec["id"]:
                collisions.append((name, written[name], rec["id"]))
                continue
            written[name] = rec["id"]
            write_json(os.path.join(OUT_DIR, name + ".json"), payload)

        if f.get("Plus Video URL"):
            date = f.get("Publish Date") or ""
            if not newest_plus or date > (newest_plus.get("date") or ""):
                newest_plus = {
                    "slug": plus_slug or slug,
                    "title": f.get("Title") or "",
                    "thumb": f.get("Thumbnail URL") or "",
                    "date": date,
                    "duration": f.get("Plus Duration") or f.get("Duration") or "",
                    "topicLine": f.get("Topic Line") or "",
                }

    if len(written) < MIN_ROWS:
        sys.exit(f"ERROR: only {len(written)} episode files built; refusing.")

    write_json(os.path.join(OUT_DIR, "_corpus.json"),
               {"generated": stamp, "count": len(corpus), "records": corpus})
    write_json(os.path.join(OUT_DIR, "_manifest.json"),
               {"generated": stamp, "count": len(written),
                "newestPlus": newest_plus})

    # Anything left in episodes/ that this run did not write is a slug that
    # no longer exists in Airtable. Left behind it would go on serving stale
    # content forever, so it goes.
    keep = {n + ".json" for n in written} | {"_corpus.json", "_manifest.json"}
    removed = 0
    for name in os.listdir(OUT_DIR):
        if name.endswith(".json") and name not in keep:
            os.remove(os.path.join(OUT_DIR, name))
            removed += 1

    total = sum(os.path.getsize(os.path.join(OUT_DIR, n))
                for n in os.listdir(OUT_DIR))
    biggest = max((os.path.getsize(os.path.join(OUT_DIR, n)), n)
                  for n in os.listdir(OUT_DIR))

    print(f"\nWrote {len(written)} files into {OUT_DIR}/ "
          f"({total / 1024 / 1024:.1f} MB total, "
          f"largest {biggest[1]} at {biggest[0] / 1024:.0f} KB)")
    print(f"  corpus: {len(corpus)} rows, "
          f"{os.path.getsize(os.path.join(OUT_DIR, '_corpus.json')) / 1024:.0f} KB")
    print(f"  newest Plus episode: {newest_plus and newest_plus['slug']}")
    if removed:
        print(f"  removed {removed} stale file(s)")
    for name, first, second in collisions:
        print(f"  WARNING: slug collision on {name}: {first} kept, {second} skipped")


if __name__ == "__main__":
    main()
