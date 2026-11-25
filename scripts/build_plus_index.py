#!/usr/bin/env python3
"""
Build plus-index.json: every live post in the members' /plus collection.

Sourced from the snapshot of the old site's /plus collection, NOT from Airtable,
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
    """An image address as stored, trimmed. Every image now lives on
    images.innerversepodcast.com, which the site sizes itself."""
    return (u or "").strip()


SITE = "https://www.innerversepodcast.com"
COLLECTION = "/plus?format=json&nojs=true"
OUT_PATH = "plus-index.json"

# Where the enrichment comes from: the per-episode files (one per Slug and
# one per Plus Slug, so a members' slug resolves directly) and the free
# index (for the old site's tags on the free post). Both are written
# earlier in the same workflow run; if either is absent the entries simply
# go out without those fields, as they did before 2026-09-25.
EPISODES_DIR = "episodes"
FREE_INDEX_PATH = "episodes-index.json"
PLUS_SNAPSHOT_PATH = "data/site-plus.json"
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
# been deleted on the old site. Once the post was gone it dropped
# out of the /plus collection entirely, so without this
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
    # 2026-11-18: the last free-only InnerVerse episodes (section B of the
    # missing /plus pages list). Chance confirmed 2026-11-14 they have no
    # members' cut (Matt Landman and David Mathisen Thor are free in full),
    # so one free page is listed in both archives, as michael-tsarion.
    "athen-chimenti-sidereal-astrology": {
        "title": "Athen Chimenti | The Inner Zodiac And True Sidereal Astrology",
        "url": SITE + "/episodes/athen-chimenti-sidereal-astrology",
        "thumb": "https://images.innerversepodcast.com/sq/shows-5a7e6d34b56c94b1216394e3/1560530869785-1e14e6db39d3570182807ace5e660737/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language"],
        "date": "2019-06-14",
    },
    "dean-mcdonnell-lusid": {
        "title": "Dean McDonnell | The LuSiDelic Experience",
        "url": SITE + "/episodes/dean-mcdonnell-lusid",
        "thumb": "https://images.innerversepodcast.com/sq/1570108250801-9asbpch90wry9cs30ec0/enlight363/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality"],
        "date": "2019-10-03",
    },
    "bluetech-evan-bartholomew-holotrope": {
        "title": "Bluetech (Evan Bartholomew) | Holotrope & Streaming Cosmic Consciousness",
        "url": SITE + "/episodes/bluetech-evan-bartholomew-holotrope",
        "thumb": "https://images.innerversepodcast.com/sq/1573481141706-91s6zbkqlss16646zdt9/image-output/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality"],
        "date": "2019-11-11",
    },
    "soohan-super-heady-spiritual": {
        "title": "Stephen Suchan | Creating Soohan: A Super Heady Spiritual Journey",
        "url": SITE + "/episodes/soohan-super-heady-spiritual",
        "thumb": "https://images.innerversepodcast.com/sq/1788877188348-4k8l1g4bkbjpwxud2c84/2020-02-26-soohan-1280x720/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality"],
        "date": "2020-02-26",
    },
    "matt-landman-questioning-coronavirus-narrative": {
        "title": "Matt Landman | Holes In The COVID-19 Narrative & The Great Panic Distraction",
        "url": SITE + "/episodes/matt-landman-questioning-coronavirus-narrative",
        "thumb": "https://images.innerversepodcast.com/sq/1788878184176-z0enbc6mwzjbusjh24jm/2020-03-30-matt-landman-1280x720/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality"],
        "date": "2020-03-30",
    },
    "athen-chimenti-2020-sidereal-astrology": {
        "title": "Athen Chimenti | Looking At 2020 Through Sidereal Astrology",
        "url": SITE + "/episodes/athen-chimenti-2020-sidereal-astrology",
        "thumb": "https://images.innerversepodcast.com/sq/1788914003189-za3w7ymbavgz5p2l2hl0/2020-08-09-athen-chimenti-1280x720/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language"],
        "date": "2020-08-10",
    },
    "john-coleman-apocatastasis": {
        "title": "John Coleman | Rethinking Education With A Higher Perspective",
        "url": SITE + "/episodes/john-coleman-apocatastasis",
        "thumb": "https://images.innerversepodcast.com/sq/1788914916584-4ibuzlxanxka1l02k4sa/2020-09-25-john-coleman-1280x720/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality"],
        "date": "2020-09-25",
    },
    "miownize-michael-martin-talking-music": {
        "title": "MioWnize - Michael Martin Talking Music",
        "url": SITE + "/episodes/miownize-michael-martin-talking-music",
        "thumb": "https://images.innerversepodcast.com/sq/1788970482177-ghpmh6hztsn2j5ved1s4/2021-03-29-miownize-music-1280x720/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Holistic Health"],
        "date": "2021-03-29",
    },
    "dylan-saccoccio-money-wealth-crypto": {
        "title": "Dylan Saccoccio | Serious Questions About Money, Wealth, Currency & Crypto",
        "url": SITE + "/episodes/dylan-saccoccio-money-wealth-crypto",
        "thumb": "https://images.innerversepodcast.com/sq/shows-5a7e6d34b56c94b1216394e3/1618235123180-31cf35e094ed600cf5122579532b432a/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Alternative History"],
        "date": "2021-04-12",
    },
    "thinking-about-13-bonus-episode": {
        "title": "Thinking About 13 (BONUS EPISODE)",
        "url": SITE + "/episodes/thinking-about-13-bonus-episode",
        "thumb": "https://images.innerversepodcast.com/sq/1639600476945-7rnj3kzqakcorcss7nzt/new-new-video-title-thumb/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality"],
        "date": "2021-12-15",
    },
    "owen-benjamin": {
        "title": "Owen Benjamin: Canceling Fear, Turning Obstacles Into Opportunity and the Spontaneous Gravy of Now",
        "url": SITE + "/episodes/owen-benjamin",
        "thumb": "https://images.innerversepodcast.com/sq/1779206701338-v21mv2dlkf34ya1282fq/owen-benjamin-canceling-fear-turning-obstacles-into-opportunity-and-the-spontaneous-gravy-of-now/orig.png",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality"],
        "date": "2022-07-18",
    },
    "music-and-sky-2022-alec-zeck-eileen-mckusick-kelly-brogan": {
        "title": "Kelly Brogan, Alec Zeck & Eileen McKusick: Knowing vs Believing | Live at Music and Sky",
        "url": SITE + "/episodes/music-and-sky-2022-alec-zeck-eileen-mckusick-kelly-brogan",
        "thumb": "https://images.innerversepodcast.com/sq/1778937274374-zgezjwzt9o04vkm4gzl3/kelly-brogan-alec-zeck-eileen-mckusick-knowing-vs-believing-live-at-music-and-sky/orig.png",
        "shows": ["Innerverse"],
        "themes": ["Holistic Health"],
        "date": "2022-10-23",
    },
    "mario-garza-symbolic-studies-chaos": {
        "title": "Mario Garza | The Temple of the Muses: Decoding Chaos and the Origin of the World",
        "url": SITE + "/episodes/mario-garza-symbolic-studies-chaos",
        "thumb": "https://images.innerversepodcast.com/sq/1667232641572-54dfybp1nri8pjodfxzu/img-3953/orig.png",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language"],
        "date": "2022-10-31",
    },
    "john-mchugh-celestial-code": {
        "title": "John McHugh | The Celestial Nativity & The Cuneiform Code of Scriptural Miracles",
        "url": SITE + "/episodes/john-mchugh-celestial-code",
        "thumb": "https://images.innerversepodcast.com/sq/1670905657204-1s70ec3hcn27rc2ih5fa/img-0057/orig.png",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language"],
        "date": "2022-12-13",
    },
    "david-mathisen-thor": {
        "title": "David Mathisen | Star Myths of the Norse: Thor, the Universal Thunderer, & the Holy World Tree",
        "url": SITE + "/episodes/david-mathisen-thor",
        "thumb": "https://images.innerversepodcast.com/sq/1676913604334-c8j93103anlhxvdkjlm4/img-1041/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language"],
        "date": "2023-02-20",
    },
    "jim-gale-food-forest": {
        "title": "Jim Gale | Freedom Through Food Forests, & Resilient Living By Building With Natural Synergy",
        "url": SITE + "/episodes/jim-gale-food-forest",
        "thumb": "https://images.innerversepodcast.com/sq/1678073421096-5tuglcz05wbl0cdagr1d/img-1223/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Holistic Health"],
        "date": "2023-03-06",
    },
    "amandha-vollmer": {
        "title": "Amandha Vollmer | The Yum Natural Doctor: Naturopathy, Right Action, & Harnessing Creativity",
        "url": SITE + "/episodes/amandha-vollmer",
        "thumb": "https://images.innerversepodcast.com/sq/1682970170035-uvb0yg6l1v2uxqryvhsg/img-1905/orig.png",
        "shows": ["Innerverse"],
        "themes": ["Holistic Health"],
        "date": "2023-05-01",
    },
    "david-mathisen-ophiuchus": {
        "title": "David Mathisen & Mario Garza | Ophiuchus Astrotheology: The Wisdom Gate to Higher Self",
        "url": SITE + "/episodes/david-mathisen-ophiuchus",
        "thumb": "https://images.innerversepodcast.com/sq/1701126690159-0f8ubtxp5yddmn8qqmds/img-3723/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality", "Myth-Symbolism-Language"],
        "date": "2023-11-28",
    },
    "john-mchugh-star-of-bethlehem": {
        "title": "John McHugh | The Royal Star of Bethlehem: Lost Celestial Origins of the Christmas Story",
        "url": SITE + "/episodes/john-mchugh-star-of-bethlehem",
        "thumb": "https://images.innerversepodcast.com/sq/1702947172765-aj425l1rwlo3sj8g403h/img-3875/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language"],
        "date": "2023-12-19",
    },
    # 2026-11-18: the 2020 Spirit Whirled livestream with Dylan Saccoccio and
    # Matt Landman predates Vibe Rant, so Chance made it an InnerVerse episode,
    # free to all, one page listed in both /episodes and /plus.
    "dylan-saccoccio-matt-landman": {
        "title": "Spirit Whirled | 8/19/20 Livestream with Dylan Saccoccio & Matt Landman",
        "url": SITE + "/episodes/dylan-saccoccio-matt-landman",
        "thumb": "https://images.innerversepodcast.com/sq/1788914132121-tuz8td0m8imd2sjt8ilk/2020-08-22-spirit-whirled-landman-1280x720/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality"],
        "date": "2020-08-22",
    },
    # 2026-11-14: Michael Tsarion was re-released in full for free, so there is
    # no members' cut; Chance: "One page goes in both archives." The free page
    # now plays the full Vimeo upload.
    "michael-tsarion": {
        "title": "Michael Tsarion | The Self & the Mysterium (Free InnerVerse Plus+ Show!)",
        "url": SITE + "/episodes/michael-tsarion",
        "thumb": "https://images.innerversepodcast.com/sq/1707179036512-o7gse8qfb3p4mhqwj0li/michael-tsarion/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Consciousness And Reality", "Myth-Symbolism-Language"],
        "date": "2024-02-06",
    },
    # 2026-11-14: Chance's 2021 guest spot on Kerri Hummingbird's Soul Nectar
    # Show, free in full (Chance Guest Spots is not in FREE_SHOWS).
    "soul-nectar-contemplating-the-innerverse": {
        "title": "Contemplating the Innerverse with Chance Garton on Soul Nectar Show",
        "url": SITE + "/episodes/soul-nectar-contemplating-the-innerverse",
        "thumb": "https://images.innerversepodcast.com/sq/chance-garton-innerverse-site-main-data-images-incoming-soul-nectar-contemplating-the-innerverse/contemplating-the-innerverse-thumbnail/orig.jpg",
        "shows": ["Chance Guest Spots"],
        "themes": ["Consciousness And Reality", "Holistic Health"],
        "date": "2021-06-27",
    },
    # 2026-11-08: Chance's guest spot on Dawn Lester's Dawn of Discernment,
    # repackaged as a free "swapcast". Chance: "same page feeding into the
    # episodes and plus pages and no distinct free/plus divides". Chance Guest
    # Spots is not in FREE_SHOWS, so it needs this one-off entry, as crrow777.
    "does-christianity-need-the-devil": {
        "title": "Does Christianity NEED the Devil? Chance Garton & Dawn Lester",
        "url": SITE + "/episodes/does-christianity-need-the-devil",
        "thumb": "https://images.innerversepodcast.com/sq/chance-garton-innerverse-site-main-data-images-incoming-does-christianity-need-the-devil/no-devil-no-priests-thumbnail/orig.jpg",
        "shows": ["Chance Guest Spots"],
        "themes": ["Myth-Symbolism-Language", "Consciousness And Reality"],
        "date": "2026-11-08",
    },
        # 2026-09-18: robert-comber-lost-octave is the reverse case again - a
    # free /episodes post with no /plus page. The guest objected to the
    # second half being paywalled, so the FULL 2h20m version was published
    # free everywhere (YouTube and Acast both carry it). Chance still wants
    # it in the members' feed, and the free-item path picks up the row's
    # Acast Audio URL, which is already the full cut.
    "robert-comber-lost-octave": {
        "title": "Robert Comber | The Lost Octave of the I Ching: Star Lore, Number, & The Cosmic Language Pattern",
        "url": SITE + "/episodes/robert-comber-lost-octave",
        "thumb": "https://images.innerversepodcast.com/sq/1713195924164-7b0l6dsjjz0kqv973zln/img-4732/orig.jpg",
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
        "thumb": "https://images.innerversepodcast.com/sq/1735662645314-598ps88wfxpxlqopdt05/img-6786/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Holistic Health"],
        "date": "2024-12-31",
    },
    "elise-frosch": {
        "title": "Elise Frosch | Preparing For Childbearing: Advice and Techniques For Ecstatic Natural Birth",
        "url": SITE + "/episodes/elise-frosch",
        "thumb": "https://images.innerversepodcast.com/sq/1720536260358-j27knl8vlm7l0woenxmv/img-5280/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Holistic Health"],
        "date": "2024-07-09",
    },
"crrow777-revelation": {
        "title": "Was the Book of Revelation Rewritten? Crrow777 w/ Chance Garton",
        "url": SITE + "/episodes/crrow-777-revelation",
        "thumb": "https://images.innerversepodcast.com/sq/1784137886568-kvuh2mf5uq9eocto04hv/crrow777-1st/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language", "Alternative History"],
        "date": "2026-07-15",
    },
    "royal-stars": {
        "title": "The Four Evangelists, Four Horsemen and the Sphinx Encode The Royal Stars",
        "url": SITE + "/episodes/royal-stars",
        "thumb": "https://images.innerversepodcast.com/sq/1779228340119-8rhvqv7vw51zuqtvz5ik/dylan-saccoccio-the-four-evangelists-are-the-four-royal-stars-and-so-are-the-four-horsemen/orig.png",
        "shows": ["Inner Whirled", "Innerverse"],
        "themes": ["Myth-Symbolism-Language"],
        "date": "2021-05-06",
    },
    "oera-linda-manuscript-a454d": {
        "title": "The Oera Linda Book Part 2: Allegory, the Holy Sailors and the Astro-Theology Beneath the Manuscript",
        "url": SITE + "/episodes/oera-linda-manuscript",
        "thumb": "https://images.innerversepodcast.com/sq/1779377198021-kz56zy5japohx4lguu8b/the-oera-linda-book-part-2-allegory-the-holy-sailors-and-the-astro-theology-beneath-the-manuscript/orig.png",
        "shows": ["Inner Whirled"],
        "themes": ["Myth-Symbolism-Language", "Alternative History"],
        "date": "2023-09-20",
    },
    "oera-linda-book-examined": {
        "title": "The Oera Linda Book: A Forbidden Frisian Manuscript Examined With Dylan Saccoccio & Slick Dissident",
        "url": SITE + "/episodes/oera-linda-book",
        "thumb": "https://images.innerversepodcast.com/sq/1779375486345-llc3580ffp3ndvz5klis/the-oera-linda-book-a-forbidden-frisian-manuscript-examined-with-dylan-saccoccio/orig.png",
        "shows": ["Inner Whirled"],
        "themes": ["Myth-Symbolism-Language", "Alternative History"],
        "date": "2023-08-23",
    },
    "jan-ott-dylan-saccoccio-oera-linda-book": {
        "title": "Jan Ott & Dylan Saccoccio | The Oera Linda Book: Linguistic Artifacts of Post-Flood Hidden History",
        "url": SITE + "/episodes/jan-ott-dylan-saccoccio-oera-linda-book",
        "thumb": "https://images.innerversepodcast.com/sq/1693163099558-82ulr2ptski9bubclv0l/img-2871/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language", "Alternative History"],
        "date": "2023-08-28",
    },
    "dylan-saccoccio-norse-phoenicians-te78l": {
        "title": "Phoenician Origins of Norse Mythology: Dylan Saccoccio on the Trail of the Holy Sailors",
        "url": SITE + "/episodes/dylan-saccoccio-norse-phoenicians-te78l",
        "thumb": "https://images.innerversepodcast.com/sq/1779280397625-u6l03nzq6nf1l06hzg7p/phoenician-origins-of-norse-mythology-dylan-saccoccio-on-the-trail-of-the-holy-sailors/orig.png",
        "shows": ["Inner Whirled", "Innerverse"],
        "themes": ["Myth-Symbolism-Language", "Alternative History"],
        "date": "2023-04-16",
    },
    "astroherbalism-gemini": {
        "title": "Gemini Astro-Herbalism: Mercury, The Air Element, & Herbal Signatures",
        "url": SITE + "/episodes/astroherbalism-gemini",
        "thumb": "https://images.innerversepodcast.com/sq/1780664773490-213vv4vpzjfh1b8n68qi/gemini-herbs-mercury-cedar-holy-basil-the-mint-mystery-astro-herbalism/orig.png",
        "shows": ["Astro-Herbalism", "Vibe Rant"],
        "themes": ["Holistic Health", "Myth-Symbolism-Language"],
        "date": "2026-06-05",
    },
    "astroherbalism-cancer": {
        "title": "Cancer Astro-Herbalism: Linden, Willow, Marshmallow & Aloe",
        "url": SITE + "/episodes/astroherbalism-cancer",
        "thumb": "https://images.innerversepodcast.com/sq/1788905125293-1hcb4ap9sao2uqetqkr0/cancer-season-herbs-linden-willow-marshmallow-aloe-astro-herbalism/orig.jpg",
        "shows": ["Astro-Herbalism", "Vibe Rant"],
        "themes": ["Holistic Health", "Myth-Symbolism-Language"],
        "date": "2026-06-17",
    },
    "leo-astroherbalism": {
        "title": "St John's Wort, Motherwort & Hawthorn: Leo Season Herbs",
        "url": SITE + "/episodes/leo-astroherbalism",
        "thumb": "https://images.innerversepodcast.com/sq/1786888416132-9h0mkv4jjkdlq2d2th11/astroherbalism-vibe-rant-leo-innerverse/orig.png",
        "shows": ["Astro-Herbalism", "Vibe Rant"],
        "themes": ["Holistic Health", "Myth-Symbolism-Language"],
        "date": "2026-08-16",
    },
    "astroherbalism-virgo": {
        "title": "Virgo Season Herbs: Gentle Plant Medicine for Digestion, Nerves & Calm",
        "url": SITE + "/episodes/astroherbalism-virgo",
        "thumb": "https://images.innerversepodcast.com/sq/1789568552495-0sktmkozux0d3hjkvl4i/astroherbalism-virgo-innerverse/orig.png",
        "shows": ["Astro-Herbalism", "Vibe Rant"],
        "themes": ["Holistic Health", "Myth-Symbolism-Language"],
        "date": "2026-09-16",
    },
    # 2026-10-21: astroherbalism-libra, the Libra remake (free only, no /plus page).
    "astroherbalism-libra": {
        "title": "Libra Herbs: What Makes a Plant Venusian?",
        "url": SITE + "/episodes/astroherbalism-libra",
        "thumb": "https://images.innerversepodcast.com/sq/11923032-4880-4cce-a7bf-bb2a4e0b52de/libra-herbs-goddess-of-balance/orig.jpg",
        "shows": ["Astro-Herbalism", "Vibe Rant"],
        "themes": ["Holistic Health", "Myth-Symbolism-Language"],
        "date": "2026-10-21",
    },
    # 2026-09-13: call-of-the-old-gods deleted from /plus (Chance confirmed:
    # the full 2-hour recording was released for free, so the Plus cut is
    # entirely redundant - the free episode's own Duration is 1h 59m, an
    # exact match for what had been the Plus-only runtime). Free page lives
    # under a different slug, same pattern as crrow777-revelation above.
    "call-of-the-old-gods": {
        "title": "The Call of the Old Gods: Paganism & the Cosmic Archetypal Psyche | Dr. Christopher McIntosh",
        "url": SITE + "/episodes/christopher-mcintosh-call-of-the-old-gods",
        "thumb": "https://images.innerversepodcast.com/sq/1750350587770-492o095qjuibujcipg3c/mcintosh-sq-thumb/orig.jpg",
        "shows": ["Innerverse"],
        "themes": ["Myth-Symbolism-Language", "Consciousness And Reality"],
        "date": "2025-06-19",
    },
    # 2026-09-18: kurtis-r-kallenbach-placenta is another free-in-full case.
    # It went out as a Vibe Rant and never got a members-only cut, so there
    # is no Vimeo upload and no /plus page to build. Chance wants it in
    # /plus browsing and in the members' feed off the row's Acast Audio URL,
    # which is the full 3h 2m show. 2026-10-01 (Chance): it is a Vibe Rant
    # only; a Vibe Rant never also carries Innerverse.
    "kurtis-r-kallenbach-placenta": {
        "title": "Your Birth Certificate Belongs to a Dead Person: The Placenta Mystery | Kurtis R. Kallenbach",
        "url": SITE + "/episodes/kurtis-r-kallenbach-placenta",
        "thumb": "https://images.innerversepodcast.com/sq/1780603254560-bagcusrq2qropm3a17ch/your-birth-certificate-belongs-to-a-dead-person-the-placenta-mystery-kurtis-r-kallenbach/orig.png",
        "shows": ["Vibe Rant"],
        "themes": ["Holistic Health", "Alternative History"],
        "date": "2023-05-10",
    },
}


def get_json(url, tries=7):
    """GET with retry/backoff. Kept for any remote read."""
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


TOPIC_TO_THEME = {
    "Consciousness & Reality": "Consciousness And Reality",
    "Myth, Symbolism, & Language": "Myth-Symbolism-Language",
    "Holistic Health": "Holistic Health",
    "Historical Investigations": "Alternative History",
}


def add_plus_page_rows(out):
    """Append an entry for every episode file whose row has Plus Page
    ticked and is not already listed. Same shape as a snapshot entry."""
    have = {p["slug"] for p in out}
    added = 0
    try:
        names = sorted(os.listdir(EPISODES_DIR))
    except FileNotFoundError:
        return 0
    seen = set()
    for name in names:
        if not name.endswith(".json") or name.startswith("_"):
            continue
        try:
            with open(os.path.join(EPISODES_DIR, name), encoding="utf-8") as fh:
                f = (json.load(fh) or {}).get("fields") or {}
        except Exception:
            continue
        if not f.get("Plus Page"):
            continue
        slug = f.get("Plus Slug") or f.get("Slug")
        if not slug or slug in have or slug in seen:
            continue
        seen.add(slug)
        shows = ["Innerverse" if s == "InnerVerse" else s for s in (f.get("Show Categories") or [])]
        themes = [TOPIC_TO_THEME[t] for t in (f.get("Topics") or []) if t in TOPIC_TO_THEME]
        out.append({
            "slug": slug,
            "title": (f.get("Title") or slug) + " (PLUS)",
            "url": SITE + "/plus/" + slug,
            "thumb": f.get("Plus Thumbnail URL") or f.get("Thumbnail URL") or "",
            "shows": shows,
            "themes": themes,
            "date": (f.get("Publish Date") or "")[:10],
        })
        added += 1
    return added


def plus_posts():
    # The /plus list as it stood on the old site at the move (2026-11-04).
    # The old collection JSON no longer exists, so it is read from a snapshot.
    with open(PLUS_SNAPSHOT_PATH, encoding="utf-8") as fh:
        out = [dict(p) for p in json.load(fh)["posts"]]

    # Merge in the redirect entries for deleted-but-still-findable episodes.
    # Guarded so a slug that is also in the snapshot is never
    # double-listed - the real post always wins.
    live_slugs = {p["slug"] for p in out}
    for slug, entry in REDIRECTS.items():
        if slug not in live_slugs:
            out.append({"slug": slug, **entry})

    # 2026-11-08: rows with "Plus Page" ticked get a members' page even
    # though they were never on the old site. Read from the episode files
    # build_episode_files.py wrote earlier in this same run.
    added = add_plus_page_rows(out)
    print(f"  {added} added by the Plus Page tick")

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


# 2026-10-01 (Chance): "vibe rant and other free shows should be on both
# pages, including this batch and any future batch". Free-only shows have
# no members' cut, so they never get a /plus post, yet members should find
# them in /plus browsing and in the private feed. Rather than a REDIRECTS
# entry per episode, every LIVE free post (it is in episodes-index.json,
# which only lists published /episodes pages) whose shows include one of
# these is added here automatically, pointing at its /episodes page. The
# REDIRECTS list above stays for one-off cases outside these shows.
# Chance Guest Spots is deliberately not included (his appearances on
# other people's shows).
FREE_SHOWS = {"vibe rant", "astro-herbalism", "marvelous demystifiers"}

# /episodes theme names -> the /plus taxonomy's names.
THEME_TO_PLUS = {
    "consciousness & reality": "Consciousness And Reality",
    "myth, symbolism, & language": "Myth-Symbolism-Language",
    "holistic health": "Holistic Health",
    "historical investigations": "Alternative History",
}


def free_show_entries(posts):
    """Entries for live free-show episodes not already in the list (by slug,
    or by the free slug a REDIRECTS url points at)."""
    free_index = read_json(FREE_INDEX_PATH) or {}
    have = set()
    for e in posts:
        have.add(e["slug"])
        have.add(free_slug_of(e))
    added = []
    for f in free_index.get("episodes") or []:
        slug = f.get("slug")
        shows = f.get("shows") or []
        if not slug or slug in have:
            continue
        if not any(s.strip().lower() in FREE_SHOWS for s in shows):
            continue
        added.append({
            "slug": slug,
            "title": f.get("title") or "",
            "url": SITE + "/episodes/" + slug,
            "thumb": clean_image_url(f.get("thumb")),
            "shows": [s for s in shows if s.strip().lower() in SHOWS],
            "themes": [THEME_TO_PLUS.get(t.strip().lower(), t) for t in (f.get("topics") or [])],
            "date": f.get("date") or "",
        })
        have.add(slug)
    return added


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
        if isinstance(f.get("Episode Number"), (int, float)):
            e["num"] = f["Episode Number"]
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
    print("Reading the /plus list ...")
    posts = plus_posts()
    print(f"  {len(posts)} posts")

    # A partial fetch must never overwrite a good index with a short one.
    # (REDIRECTS entries count toward this floor too, which is fine - the
    # live fetch still has to clear ~40 on its own for this to pass.)
    if len(posts) < 40:
        sys.exit("ERROR: /plus returned suspiciously few posts; refusing to write.")

    extra = free_show_entries(posts)
    if extra:
        posts.extend(extra)
        posts.sort(key=lambda e: (e["date"] or ""), reverse=True)
    print(f"  {len(extra)} free-show episodes added from {FREE_INDEX_PATH}")

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
