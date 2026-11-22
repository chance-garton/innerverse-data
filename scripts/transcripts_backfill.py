#!/usr/bin/env python3
"""Transcripts for the older free /episodes pages (the backfill, 2026-11-22).

Run by .github/workflows/transcripts.yml, never by hand with a real token in a
chat: a transcript is too big to pass through a chat session cheaply, so the
whole job stays inside GitHub Actions.

    python scripts/transcripts_backfill.py --count 40 --mode test --site site

For each live free page (slug in episodes-index.json) whose Airtable row has a
free "Transcript File" and no transcript yet (transcripts/<slug>.json here, or
data/transcripts/<slug>.json in the site repo), newest Publish Date first,
Chance Guest Spots left out, it:

  1. downloads the attachment (only the free "Transcript File" field is ever
     requested from Airtable; the members' transcript field is never read),
  2. turns it into block format with the site repo's
     tools/episode-notes/normalize_transcript.py,
  3. builds the page JSON with the site repo's tools/episode-notes/build_transcript.py
     (both are read from a checkout of innerverse-site at run time, not copied
     here, so there is one copy of each),
  4. applies the per row name fixes in transcripts/_name_fixes.json,
  5. checks the result: first paragraph under 60 s, last paragraph within
     5 percent of the free runtime (Duration), at least 3,000 words, no em or
     en dashes, a guest's name present when the row has guests.

mode test:  writes transcripts/_report.json and the built files to _test_out/
            (the workflow keeps both as a run artifact). Nothing is committed.
mode apply: also writes each passing file to transcripts/<slug>.json for the
            workflow to commit. Failures stay out and are listed in the report.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_ID = "appg1ujebSIw7TyFW"
EPISODES_TABLE = "tbl8lZF3m1yZZ1hcQ"
GUESTS_TABLE = "tblq0USTWxfIEYiKV"

# Field IDs (stable across renames). Only these are requested.
F_SLUG = "fld9pDFBRiZYNl8IR"
F_TITLE = "fldGbtuFLmXQhpRj3"
F_SHOW = "fldybBioI013N0nva"          # single select show
F_SHOWS = "fld9Ljoj6WcnhudCr"         # Show Categories
F_DATE = "fldriTOlSEOUxDdYe"          # Publish Date
F_DURATION = "fld6Zajp8Ami13S6V"      # Duration of the free cut, "1h 36m"
F_VIDEO = "fldf3R6oRcg1Osqfc"         # Video URL (free)
F_GUESTS = "fldhrTolEQpztEBCL"
F_TRANSCRIPT = "fldJV3ZGrjPSPLt0O"    # Transcript File (FREE transcript only)
F_OFFSET = "fldIdVE9Rirax4Ic9"        # Audio Offset Seconds
F_GUEST_NAME = "fld5YGyyN9zmfXdz4"

HOST_NAMES = {"chance garton"}
GUEST_SPOTS = "Chance Guest Spots"
MIN_WORDS = 3000
FIRST_MAX = 60
END_TOLERANCE = 0.05

TOKEN = os.environ.get("AIRTABLE_TOKEN", "").strip()


def get(url, headers=None, tries=6, raw=False):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": "innerverse-transcripts", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
                return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                time.sleep(min(60, 3 * 2 ** attempt))
                continue
            raise
        except Exception:
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def airtable_all(table, fields):
    out, offset = [], None
    headers = {"Authorization": "Bearer " + TOKEN}
    while True:
        params = [("pageSize", "100"), ("returnFieldsByFieldId", "true")] + [("fields[]", f) for f in fields]
        if offset:
            params.append(("offset", offset))
        data = get("https://api.airtable.com/v0/%s/%s?%s" % (BASE_ID, table, urllib.parse.urlencode(params)), headers)
        out.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            return out
        time.sleep(0.25)


def runtime_seconds(s):
    """'1h 36m', '52m', '1h 36m 10s' or '1:36:10' to seconds; None if unreadable."""
    s = (s or "").strip().lower()
    if not s:
        return None
    if re.fullmatch(r"\d+(:\d+){1,2}", s):
        n = 0
        for part in s.split(":"):
            n = n * 60 + int(part)
        return n
    units = {"h": 3600, "m": 60, "s": 1}
    found = re.findall(r"(\d+)\s*([hms])", s)
    if not found:
        return None
    return sum(int(v) * units[u] for v, u in found)


def choose_attachment(atts):
    for a in atts:
        if (a.get("filename") or "").lower().endswith(".txt"):
            return a
    return atts[0] if atts else None


def apply_fixes(paras, fixes):
    for wrong, right in fixes:
        pat = re.compile(r"\b" + re.escape(wrong) + r"\b")
        for p in paras:
            p["text"] = pat.sub(right, p["text"])


def name_found(text, names):
    """True when any guest's full name, or a first or last name of four or more
    letters, appears in the text (case ignored)."""
    low = text.lower()
    for n in names:
        if n.lower() in low:
            return True
        parts = [w for w in re.findall(r"[A-Za-z']+", n) if len(w) >= 4]
        if any(re.search(r"\b" + re.escape(w.lower()) + r"\b", low) for w in parts):
            return True
    return False


def check(paras, runtime, guests):
    reasons = []
    if not paras:
        return ["no paragraphs built"]
    words = sum(len(p["text"].split()) for p in paras)
    first, last = paras[0]["seek"], paras[-1]["seek"]
    if first >= FIRST_MAX:
        reasons.append("first paragraph starts at %ds (60 s or more)" % first)
    if runtime:
        gap = runtime - last
        if abs(gap) > END_TOLERANCE * runtime:
            if gap > 0:
                reasons.append("ends at %ds, %ds before the %ds runtime (short coverage)" % (last, gap, runtime))
            else:
                reasons.append("runs to %ds, past the %ds runtime (a longer cut?)" % (last, runtime))
    else:
        reasons.append("no free runtime (Duration) on the row")
    if words < MIN_WORDS:
        reasons.append("only %d words" % words)
    blob = " ".join(p["text"] for p in paras)
    if re.search("[–—]", blob):
        reasons.append("contains an em or en dash")
    if guests and not name_found(blob, guests):
        reasons.append("no guest name found (" + ", ".join(guests) + "): misspelled?")
    return reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--mode", choices=["test", "apply"], default="test")
    ap.add_argument("--source", choices=["airtable", "youtube"], default="airtable")
    ap.add_argument("--site", default="site", help="checkout of innerverse-site")
    args = ap.parse_args()

    if args.source == "youtube":
        sys.exit("source=youtube is part C of the job and is not built yet.")
    if not TOKEN:
        sys.exit("ERROR: AIRTABLE_TOKEN is not set.")

    tools = os.path.join(args.site, "tools", "episode-notes")
    normalize = os.path.join(tools, "normalize_transcript.py")
    builder = os.path.join(tools, "build_transcript.py")
    for p in (normalize, builder):
        if not os.path.exists(p):
            sys.exit("ERROR: missing " + p + " (is the site repo checked out at the right ref?)")

    live = {e["slug"] for e in json.load(open("episodes-index.json", encoding="utf-8"))["episodes"]}
    fixes_all = {}
    if os.path.exists("transcripts/_name_fixes.json"):
        fixes_all = json.load(open("transcripts/_name_fixes.json", encoding="utf-8"))

    def has_transcript(slug):
        return (os.path.exists(os.path.join("transcripts", slug + ".json"))
                or os.path.exists(os.path.join(args.site, "data", "transcripts", slug + ".json")))

    print("Fetching guests ...")
    guest_name = {r["id"]: (r.get("fields") or {}).get(F_GUEST_NAME) for r in airtable_all(GUESTS_TABLE, [F_GUEST_NAME])}
    print("Fetching episodes ...")
    rows = airtable_all(EPISODES_TABLE, [F_SLUG, F_TITLE, F_SHOW, F_SHOWS, F_DATE, F_DURATION, F_VIDEO,
                                         F_GUESTS, F_TRANSCRIPT, F_OFFSET])
    print("  %d rows" % len(rows))

    queue, counts = [], {"live with file": 0, "already done": 0, "guest spots": 0}
    for r in rows:
        f = r.get("fields") or {}
        slug = f.get(F_SLUG)
        if not slug or slug not in live or not f.get(F_TRANSCRIPT):
            continue
        counts["live with file"] += 1
        shows = list(f.get(F_SHOWS) or [])
        show = f.get(F_SHOW)
        if isinstance(show, dict):
            show = show.get("name")
        if show:
            shows.append(show)
        if GUEST_SPOTS in shows:
            counts["guest spots"] += 1
            continue
        if has_transcript(slug):
            counts["already done"] += 1
            continue
        queue.append(f)
    queue.sort(key=lambda f: (f.get(F_DATE) or "0000", f.get(F_SLUG)), reverse=True)
    ready_left = len(queue)
    batch = queue[:args.count]
    print("  %d READY waiting, taking %d (%s)" % (ready_left, len(batch), counts))

    os.makedirs("transcripts", exist_ok=True)
    os.makedirs("_test_out", exist_ok=True)
    results = []
    for f in batch:
        slug = f[F_SLUG]
        guests = [guest_name.get(g) for g in (f.get(F_GUESTS) or [])]
        guests = [g for g in guests if g and g.strip().lower() not in HOST_NAMES]
        runtime = runtime_seconds(f.get(F_DURATION))
        item = {"slug": slug, "title": f.get(F_TITLE), "date": f.get(F_DATE), "duration": f.get(F_DURATION),
                "audioOffset": f.get(F_OFFSET) or 0, "guests": guests}
        att = choose_attachment(f.get(F_TRANSCRIPT) or [])
        item["file"] = att.get("filename") if att else None
        try:
            if not att:
                raise ValueError("no attachment")
            if not (att.get("filename") or "").lower().endswith(".txt"):
                raise ValueError("not a .txt file: %s" % att.get("filename"))
            data = get(att["url"], raw=True)
            with tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, "in.txt")
                norm = os.path.join(tmp, "norm.txt")
                built = os.path.join(tmp, "out.json")
                open(src, "wb").write(data)
                n = subprocess.run([sys.executable, "-I", normalize, src, norm], capture_output=True, text=True)
                if n.returncode:
                    raise ValueError("convert: " + (n.stderr or n.stdout).strip().splitlines()[-1])
                item["format"] = n.stdout.split()[0] if n.stdout.strip() else "?"
                total = runtime or 0
                if not total:
                    # No runtime on the row: let the last block run 60 s; the check fails it anyway.
                    stamps = re.findall(r"\((?:(\d+):)?(\d+):(\d+)", open(norm, encoding="utf-8").read())
                    total = max((int(h or 0) * 3600 + int(m) * 60 + int(s) for h, m, s in stamps), default=0) + 60
                b = subprocess.run([sys.executable, "-I", builder, norm, str(total), built], capture_output=True, text=True)
                if b.returncode:
                    err = (b.stderr or b.stdout).strip().splitlines()
                    msg = err[-1] if err else "failed"
                    if "AssertionError" in msg:
                        msg = "the source has em or en dashes"
                    raise ValueError("build: " + msg)
                paras = json.load(open(built, encoding="utf-8"))
            apply_fixes(paras, fixes_all.get("*", []) + fixes_all.get(slug, []))
            item["paragraphs"] = len(paras)
            item["words"] = sum(len(p["text"].split()) for p in paras)
            item["firstSeek"] = paras[0]["seek"] if paras else None
            item["lastSeek"] = paras[-1]["seek"] if paras else None
            item["runtimeSeconds"] = runtime
            reasons = check(paras, runtime, guests)
            item["status"] = "fail" if reasons else "pass"
            item["reasons"] = reasons
            dest = os.path.join("transcripts" if (args.mode == "apply" and not reasons) else "_test_out", slug + ".json")
            json.dump(paras, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        except Exception as e:  # one bad row never stops the batch
            item["status"] = "fail"
            item["reasons"] = [str(e)[:300]]
        print("%-4s %s %s" % (item["status"].upper(), slug, "; ".join(item.get("reasons") or [])))
        results.append(item)

    report = {
        "generated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "mode": args.mode,
        "count": args.count,
        "readyBefore": ready_left,
        "counts": counts,
        "passed": sum(1 for r in results if r["status"] == "pass"),
        "failed": sum(1 for r in results if r["status"] == "fail"),
        "results": results,
    }
    json.dump(report, open("transcripts/_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("passed %d, failed %d" % (report["passed"], report["failed"]))

    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as fh:
            fh.write("## Transcripts %s: %d passed, %d failed (%d READY before this run)\n\n" % (
                args.mode, report["passed"], report["failed"], ready_left))
            fh.write("| | slug | date | words | first | last | runtime | why |\n|---|---|---|---|---|---|---|---|\n")
            for r in results:
                fh.write("| %s | %s | %s | %s | %s | %s | %s | %s |\n" % (
                    "ok" if r["status"] == "pass" else "FAIL", r["slug"], r.get("date") or "",
                    r.get("words", ""), r.get("firstSeek", ""), r.get("lastSeek", ""),
                    r.get("runtimeSeconds", ""), "; ".join(r.get("reasons") or [])))


if __name__ == "__main__":
    main()
