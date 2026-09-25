#!/usr/bin/env python3
"""
IRS Exempt Organizations Business Master File (eo1-4.csv, irs.gov/pub/irs-soi/)
filtered by NTEE activity code. Keyless, ~340MB total, ~1.96M orgs nationwide.

NTEE_CD G84 = Autism, H84 = Autism research. Per the 2026-09-25 research note
(~/Desktop/autism-registry-sources-2026-09-25.md), 718 of these orgs don't
contain "autism" in their name at all (e.g. "Rock the Spectrum Corporation"),
so the existing ProPublica-based name search misses them entirely -- the
single biggest documented autism gap in the whole pipeline as of this pass.

Also pulls the disability-layer NTEE codes for the second/third data layer
(P82 developmentally disabled centers, B28 special education, E50
rehabilitative care, R23 disabled persons' rights, P86 blind/visually
impaired, P87 deaf/hearing impaired, G25 birth defects & genetic conditions
incl. Down syndrome) -- tagged disability_scope so they stay a separate,
filterable layer rather than mixed into the autism-tagged core.

Usage:
    curl -o /tmp/eo1.csv https://www.irs.gov/pub/irs-soi/eo1.csv
    curl -o /tmp/eo2.csv https://www.irs.gov/pub/irs-soi/eo2.csv
    curl -o /tmp/eo3.csv https://www.irs.gov/pub/irs-soi/eo3.csv
    curl -o /tmp/eo4.csv https://www.irs.gov/pub/irs-soi/eo4.csv
    python3 tools/irs_bmf_ntee_fetch.py
"""
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["/tmp/eo1.csv", "/tmp/eo2.csv", "/tmp/eo3.csv", "/tmp/eo4.csv"]

AUTISM_CODES = {"G84", "H84"}
DISABILITY_CODES = {
    "P82": "neurodevelopmental",  # developmentally disabled centers
    "B28": "neurodevelopmental",  # special education
    "E50": "general",             # rehabilitative medical services
    "R23": "general",             # disabled persons' rights
    "P86": "general",             # blind/visually impaired
    "P87": "general",             # deaf/hearing impaired
    "G25": "neurodevelopmental",  # birth defects & genetic conditions (incl. Down syndrome)
}

UA = {"User-Agent": "autism-community-resources research (contact: changcheng875@gmail.com)"}


def geocode(query):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "limit": 1, "countrycodes": "us"}
    )
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
        if data:
            return {"lat": float(data[0]["lat"]), "lng": float(data[0]["lon"])}
    except Exception:
        pass
    return None


def clean_addr(row):
    street = (row.get("STREET") or "").strip()
    city = (row.get("CITY") or "").strip()
    state = (row.get("STATE") or "").strip()
    zipc = (row.get("ZIP") or "").strip().split("-")[0]
    parts = [p for p in [street, city, state, zipc] if p]
    return ", ".join(parts), street, city, state, zipc


def main():
    for f in FILES:
        if not os.path.exists(f):
            print(f"Missing {f} -- download the 4 eo*.csv files first (see docstring).")
            sys.exit(1)

    autism_rows = []
    disability_rows = []
    for path in FILES:
        with open(path, encoding="latin-1") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ntee = (row.get("NTEE_CD") or "").strip()
                code3 = ntee[:3]
                if code3 in AUTISM_CODES:
                    autism_rows.append(row)
                elif code3 in DISABILITY_CODES:
                    disability_rows.append((row, DISABILITY_CODES[code3]))

    print(f"Autism NTEE (G84/H84): {len(autism_rows)} raw rows")
    print(f"Disability-layer NTEE: {len(disability_rows)} raw rows")

    seen_ein = set()
    out = []

    def build_entry(row, scope):
        ein = (row.get("EIN") or "").strip()
        if not ein or ein in seen_ein:
            return None
        seen_ein.add(ein)
        name = (row.get("NAME") or "").strip().title()
        addr, street, city, state, zipc = clean_addr(row)
        if not name or not city or not state:
            return None
        entry = {
            "name": name,
            "address": addr,
            "phone": "",
            "website": "",
            "type": "general_support",
            "source": "IRS Exempt Organizations Business Master File (NTEE)",
            "services": [],
            "description": f"IRS-registered tax-exempt organization, NTEE code {(row.get('NTEE_CD') or '').strip()}. EIN {ein}.",
            "coordinates": None,
            "suggested": {},
            "entity_type": "organization",
            "ein": ein,
            "_city": city,
            "_state": state,
        }
        if scope != "autism":
            entry["disability_scope"] = scope
        return entry, addr

    to_geocode = []
    for row in autism_rows:
        built = build_entry(row, "autism")
        if built:
            out.append(built[0])
            to_geocode.append((built[0], built[1]))

    # Disability-layer NTEE codes (~8,400 raw rows) are deliberately NOT
    # geocoded/merged in this pass -- at Nominatim's 1req/sec usage policy
    # that's ~2.5 hours alone, and priority-0 is specifically the autism
    # gap. Left as a documented follow-up (see HANDOFF.md); re-run this
    # script with INCLUDE_DISABILITY=1 to also build that layer.
    if os.environ.get("INCLUDE_DISABILITY"):
        for row, scope in disability_rows:
            built = build_entry(row, scope)
            if built:
                out.append(built[0])
                to_geocode.append((built[0], built[1]))
    else:
        print(f"Skipping {len(disability_rows)} disability-layer raw rows this pass (set INCLUDE_DISABILITY=1 to include)")

    print(f"After EIN de-dup: {len(out)} unique orgs to geocode")

    # Geocode by unique (city, state) pair rather than per-org: far fewer
    # Nominatim calls than one per org, at city-level precision -- same
    # fallback-to-city tradeoff already used elsewhere in this pipeline
    # (Latvia, Netherlands ANBI, Bulgaria) when a street address won't
    # resolve or precision isn't worth the extra calls.
    city_cache = {}
    for i, (entry, addr) in enumerate(to_geocode):
        row = entry
        key = (row.get("_city", ""), row.get("_state", ""))
        if key not in city_cache:
            q = f"{key[0]}, {key[1]}, USA"
            city_cache[key] = geocode(q)
            time.sleep(1.05)  # Nominatim usage policy: max 1 req/sec
            if i % 50 == 0:
                print(f"  geocoded {i}/{len(to_geocode)} ({len(city_cache)} unique cities so far)")
        coords = city_cache[key]
        if coords:
            entry["coordinates"] = coords
            entry["placeless"] = False
        else:
            entry["placeless"] = True
        entry.pop("_city", None)
        entry.pop("_state", None)

    with open(os.path.join(REPO, "new_resources_irs_bmf_ntee.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(out)} entries to new_resources_irs_bmf_ntee.json")


if __name__ == "__main__":
    main()
