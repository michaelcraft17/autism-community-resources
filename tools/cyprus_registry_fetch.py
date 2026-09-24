#!/usr/bin/env python3
"""
Cypriot autism-related associations from the official Register of
Associations, Foundations, Federations and Unions (Μητρώο Εγγεγραμμένων
Σωματείων, Ιδρυμάτων, Ομοσπονδιών ή Ενώσεων), published as open data:

    https://data.gov.cy/dataset/mitroo-eggegrammenon-somateion-idrymaton-omospondion-i-enoseon

Free, no API key, CSV download. The dataset page itself was found by
using data.gov.cy's own Drupal search (`/search?s=<term>`) rather than
guessing a CKAN-style API path -- this portal isn't CKAN, and its
`/api/3/action/...` paths 404.

Small yield (Cyprus has ~920K people): 5 raw keyword matches, 4 kept.
One ("ΥΠΟ ΕΞΕΤΑΣΗ" / "under review") is excluded -- not yet an approved,
active registration, same discipline as excluding "struck off"/
"in liquidatie" entries in tools/belgium_kbo_fetch.py and
tools/netherlands_anbi_fetch.py.

No street address in this dataset, only a district name -- entries are
geocoded to the district's main city.

Usage:
    python3 tools/cyprus_registry_fetch.py

Writes:
    tools/cyprus_registry_scratch/registry.csv   raw downloaded CSV (gitignored)
    new_resources_cyprus.json                     final resource-schema output (repo root)
"""
import csv
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "cyprus_registry_scratch")
os.makedirs(SCRATCH, exist_ok=True)
CSV_PATH = os.path.join(SCRATCH, "registry.csv")
OUT_PATH = os.path.join(REPO, "new_resources_cyprus.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
CSV_URL = ("https://data.gov.cy/sites/default/files/"
           "%CE%95%CE%B3%CE%B3%CE%B5%CE%B3%CF%81%CE%B1%CE%BC%CE%BC%CE%AD%CE%BD%CE%B1%20"
           "%CE%BA%CE%B1%CE%B9%20%CE%A5%CF%80%CE%BF%20%CE%95%CE%BE%CE%AD%CF%84%CE%B1%CF%83%CE%B7%20"
           "%CE%A3%CF%89%CE%BC%CE%B1%CF%84%CE%B5%CE%AF%CE%B1%20-%20%CE%99%CE%B4%CF%81%CF%8D%CE%BC%CE%B1%CF%84%CE%B1_1.csv")
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Cyprus Register of Associations, Foundations, Federations and Unions - official open data"

KEYWORD = "αυτισμ"
EXCLUDE_STATUS_SUBSTR = ["ΥΠΟ ΕΞΕΤΑΣΗ"]  # "under review" -- not yet an approved registration

DISTRICT_CITY = {
    "ΛΕΥΚΩΣΙΑΣ": "Nicosia", "ΛΕΥΚΩΣΙΑ": "Nicosia",
    "ΛΑΡΝΑΚΑΣ": "Larnaca", "ΛΑΡΝΑΚΑ": "Larnaca",
    "ΑΜΜΟΧΩΣΤΟΣ": "Famagusta", "ΑΜΜΟΧΩΣΤΟΥ": "Famagusta",
    "ΛΕΜΕΣΟΣ": "Limassol", "ΛΕΜΕΣΟΥ": "Limassol",
    "ΠΑΦΟΣ": "Paphos", "ΠΑΦΟΥ": "Paphos",
}


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
    print("Fetching Cyprus association/foundation registry...")
    download_csv()

    matches = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Name") or "").strip()
            status = (row.get("Category") or "").strip()
            if KEYWORD not in name.lower():
                continue
            if any(x in status for x in EXCLUDE_STATUS_SUBSTR):
                print(f"  skipping (not yet approved): {name}")
                continue
            matches.append({"name": name, "district": (row.get("District") or "").strip()})
    print(f"  {len(matches)} matches after status filter")

    resources = []
    for m in matches:
        city = DISTRICT_CITY.get(m["district"])
        address = f"{city}, Cyprus" if city else "Cyprus"
        coords = geocode(address) if city else None
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec

        entry = {
            "name": m["name"],
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": f"Registered association in Cyprus's official association/foundation registry"
                            + (f", {city} district." if city else "."),
            "address": address,
        }
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        resources.append(entry)
        print(f"  {m['name']}: {'geocoded' if coords else 'placeless'}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} geocoded")


if __name__ == "__main__":
    main()
