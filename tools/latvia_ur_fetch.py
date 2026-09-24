#!/usr/bin/env python3
"""
Latvian autism-related associations and foundations from the Register
of Enterprises (Uzņēmumu reģistrs)'s official open-data extract of
every registered association/foundation (biedrības un nodibinājumi),
published via the national open-data portal:

    https://data.gov.lv/dati/dataset/49a0f06b-2d2b-4368-8ed5-676a05244f6a

Free, no API key, CC-licensed bulk CSV (regcode;name;type;area_of_activity
-- one row per org per activity-area tag, so an org can appear on
multiple rows). Same tier of source as tools/netherlands_anbi_fetch.py's
ANBI register: an official government open dataset, not scraped or
LLM-narrated.

Known false-positive pattern, same class as "nautisch"/"nautical" in
tools/belgium_kbo_fetch.py and tools/netherlands_anbi_fetch.py:
Latvian "starptautisks"/"starptautiska" (international) contains
"autis" as a substring ("st-arpt-AUTIS-ka") purely by coincidence --
excluded explicitly below.

No street address in this dataset (just name/regcode/type/activity
area), so entries are placeless (country-level) unless the
organization's own name names a specific city, in which case that
city is used for a coarse geocode -- same discipline as ANBI's
city-only geocoding.

Usage:
    python3 tools/latvia_ur_fetch.py

Writes:
    tools/latvia_ur_scratch/register.csv   raw downloaded CSV (gitignored)
    new_resources_latvia.json               final resource-schema output (repo root)
"""
import csv
import io
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "latvia_ur_scratch")
os.makedirs(SCRATCH, exist_ok=True)
CSV_PATH = os.path.join(SCRATCH, "register.csv")
OUT_PATH = os.path.join(REPO, "new_resources_latvia.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
CSV_URL = ("https://data.gov.lv/dati/dataset/49a0f06b-2d2b-4368-8ed5-676a05244f6a/"
           "resource/263f7def-5df6-45ed-a747-81e1d48a48c4/download/"
           "areas_of_activity_of_associations_foundations.csv")
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Latvia Register of Enterprises (Uzņēmumu reģistrs) open data - official associations/foundations register"

KEYWORD = "autis"
EXCLUDE_SUBSTR = ["starptautisk", "tautisk"]  # "international" false-positive, see docstring

# Latvian city names to try extracting from an org's own name for a coarse geocode.
KNOWN_CITIES = ["Daugavpils", "Rēzekne", "Rēzeknē", "Rīga", "Liepāja", "Jelgava", "Ventspils", "Latgale", "Latgales"]


def download_csv():
    if os.path.exists(CSV_PATH):
        print(f"  using cached {CSV_PATH}")
        return
    req = urllib.request.Request(CSV_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with open(CSV_PATH, "wb") as f:
        f.write(data)
    print(f"  downloaded to {CSV_PATH}")


def geocode(query):
    params = {"q": query, "format": "json", "limit": 1}
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.loads(resp.read())
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception as e:
        print(f"  geocode failed for {query!r}: {e}")
    return None


def main():
    print("Fetching Latvia Register of Enterprises associations/foundations extract...")
    download_csv()

    seen = {}
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        for row in reader:
            if len(row) < 3:
                continue
            regcode, name = row[0], row[1]
            low = name.lower()
            if KEYWORD not in low:
                continue
            if any(x in low for x in EXCLUDE_SUBSTR):
                continue
            seen.setdefault(regcode, name)
    print(f"  {len(seen)} unique matching organizations")

    resources = []
    for regcode, name in seen.items():
        # The quote marks here are part of the org's actual registered name
        # (a common Latvian convention for a sub-name, e.g. Fonds ""VALENSIA""),
        # not a CSV-parsing artifact -- keep them as-is, just collapse whitespace.
        clean_name = re.sub(r"\s+", " ", name).strip()
        # NFC-normalize before substring matching: the source CSV and this
        # script's literal Latvian text can use different Unicode compositions
        # for the same visible diacritics (e.g. precomposed vs. combining "ē").
        norm_name = unicodedata.normalize("NFC", clean_name)
        city = next((c for c in KNOWN_CITIES if unicodedata.normalize("NFC", c) in norm_name), None)
        coords = None
        address = "Latvia"
        if city:
            city_query = city[:-1] + "e" if city.endswith("ē") else city  # "Rēzeknē" (locative) -> "Rēzekne"
            coords = geocode(f"{city_query}, Latvia")
            time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
            address = f"{city_query}, Latvia"

        entry = {
            "name": clean_name,
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": f"Registered association/foundation in the Latvian Register of Enterprises.",
            "address": address,
        }
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        resources.append(entry)
        print(f"  {clean_name}: {'geocoded' if coords else 'placeless'}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} geocoded")


if __name__ == "__main__":
    main()
