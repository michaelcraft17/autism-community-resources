#!/usr/bin/env python3
"""
Inclusion International full member listing (round-4 research, section 3).

Global intellectual-disability federation. Its member-listing page
(https://inclusion-international.org/our-members/full-member-listing/,
paginated /page/N/, 11 pages) has no per-member website link on the listing
page itself (checked directly -- round 4's "with website" claim appears to
require visiting each member's own sub-page, not done here; a follow-up
could enrich websites separately). What IS on the listing page: country,
org name, region, and a short description -- an official umbrella body's own
member list, the same accepted tier as the existing Autism-Europe fetcher.

No street address is published, only country -- entries are geocoded to a
country-level centroid (Nominatim, no house-number precision expected or
needed) and tagged disability_scope="general" (intellectual/developmental
disability, not autism-specific).

Usage:
    python3 tools/inclusion_international_fetch.py
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from category_map import classify

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://inclusion-international.org/our-members/full-member-listing/"
UA = {"User-Agent": "autism-community-resources research (contact: changcheng875@gmail.com)"}
OUT = os.path.join(REPO, "new_resources_inclusion_international.json")

ITEM_RE = re.compile(
    r'flag-info">([^<]+)</span></p><h2[^>]*><span>([^<]+)</span></h2>'
    r'<p class="post-item-heading-sub">([^<]*)</p></div></div>'
    r'<div class="post-item-text"><p class="post-item-teaser"[^>]*>([^<]*)</p>',
    re.S,
)


def fetch_page(n):
    url = BASE if n == 1 else f"{BASE}page/{n}/"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def geocode_country(country, cache):
    if country in cache:
        return cache[country]
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": country, "format": "json", "limit": 1}
    )
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
        coords = {"lat": float(data[0]["lat"]), "lng": float(data[0]["lon"])} if data else None
    except Exception:
        coords = None
    cache[country] = coords
    time.sleep(1.05)
    return coords


def main():
    all_items = []
    n = 1
    while True:
        page_html = fetch_page(n)
        matches = ITEM_RE.findall(page_html)
        if not matches:
            break
        all_items.extend(matches)
        print(f"page {n}: {len(matches)} members")
        n += 1
        if n > 20:  # safety cap
            break

    print(f"Total members found: {len(all_items)}")

    geo_cache = {}
    out = []
    for country, name, region, teaser in all_items:
        country = html.unescape(country.strip())
        name = html.unescape(name.strip())
        teaser = html.unescape(teaser.strip())
        coords = geocode_country(country, geo_cache)
        entry = {
            "name": name,
            "address": country,
            "phone": "",
            "website": "",
            "type": classify(name, teaser),
            "source": "Inclusion International full member listing (global intellectual-disability federation) - official umbrella-body member directory",
            "services": [],
            "description": teaser,
            "disability_scope": "general",
        }
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        out.append(entry)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"Wrote {len(out)} entries to {OUT}")


if __name__ == "__main__":
    main()
