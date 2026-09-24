#!/usr/bin/env python3
"""
Czech autism-related organizations from ARES (Administrativní registr
ekonomických subjektů / Administrative Register of Economic Subjects) --
the Czech Ministry of Finance's official register of every legal entity
in the Czech Republic:

    https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/vyhledat

Free, no API key, modern REST/JSON search endpoint (POST with a JSON
body). Same tier of source as tools/norway_brreg_fetch.py's
Bronnoysund register or tools/czech_ares_fetch.py's own Czech
counterpart -- an official government registry, not scraped or
LLM-narrated. Each result's `sidlo.textovaAdresa` field is a
ready-to-use, pre-formatted address string, so no separate geocoding
address-assembly step is needed (only the geocode lookup itself).

Small yield (this is a country of ~10.5M people): querying literal
Czech autism-root terms (autismus, autiste) surfaces 7 real
organizations, no false positives found (unlike the "nautisch"-style
substring collisions seen in Belgium/Netherlands/Norway/Finland).

Usage:
    python3 tools/czech_ares_fetch.py

Writes:
    tools/czech_ares_scratch/raw_<term>.json   raw API responses (gitignored)
    new_resources_czech.json                    final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "czech_ares_scratch")
os.makedirs(SCRATCH, exist_ok=True)
OUT_PATH = os.path.join(REPO, "new_resources_czech.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)",
           "Content-Type": "application/json"}
API = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/vyhledat"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Czech Republic ARES (Administrative Register of Economic Subjects) - official national entity registry"

SEARCH_TERMS = ["autismus", "autiste", "autisté"]


def fetch_term(term):
    safe = term.encode("ascii", "ignore").decode() or "term"
    cache = os.path.join(SCRATCH, f"raw_{safe}.json")
    if os.path.exists(cache):
        print(f"  using cached {cache}")
        return json.load(open(cache, encoding="utf-8"))
    body = json.dumps({"obchodniJmeno": term, "pocet": 50}).encode("utf-8")
    req = urllib.request.Request(API, data=body, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    entities = data.get("ekonomickeSubjekty", [])
    json.dump(entities, open(cache, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"  {term}: {len(entities)} raw hits from API")
    return entities


def geocode(address):
    params = {"q": address, "format": "json", "limit": 1}
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.loads(resp.read())
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception as e:
        print(f"  geocode failed for {address!r}: {e}")
    return None


def main():
    print("Fetching Czech ARES register...")
    all_entities = {}
    for term in SEARCH_TERMS:
        for e in fetch_term(term):
            all_entities[e["ico"]] = e
        time.sleep(1.1)
    print(f"  {len(all_entities)} unique entities across all search terms")

    resources = []
    for e in all_entities.values():
        name = e.get("obchodniJmeno", "").strip()
        sidlo = e.get("sidlo") or {}
        addr_text = sidlo.get("textovaAdresa")
        full_address = f"{addr_text}, Czech Republic" if addr_text else "Czech Republic"

        coords = geocode(full_address)
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec

        entry = {
            "name": name,
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": f"Registered organization in the Czech ARES national registry, based in {sidlo.get('nazevObce', 'the Czech Republic')}.",
            "address": full_address,
        }
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        resources.append(entry)
        print(f"  {name}: {'geocoded' if coords else 'NOT geocoded (placeless)'}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} geocoded")


if __name__ == "__main__":
    main()
