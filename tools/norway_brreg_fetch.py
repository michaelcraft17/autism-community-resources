#!/usr/bin/env python3
"""
Norwegian autism-related entities from Brønnøysundregistrene (the Brønnøysund
Register Centre) -- Norway's official central register of every registered
business, association, foundation, and sole proprietorship in the country:

    https://data.brreg.no/enhetsregisteret/api/enheter

Free, no API key, no rate limit documented (used politely here with a
delay anyway). Same tier of source as tools/france_rna_fetch.py's RNA or
tools/netherlands_anbi_fetch.py's ANBI register: an official government
registry, not scraped or LLM-narrated.

Quirk: the API's `navn` query param does fuzzy/approximate matching, not
substring search -- querying "autist" returns hundreds of unrelated hits
(e.g. every entity named "AUGUST ...", which is a near-miss on edit
distance). This script queries clean literal Norwegian autism-root terms
(autisme, autistisk, autist) and then filters client-side by checking the
name actually contains "autis" as a substring (case-insensitive) --
deliberately not trusting the API's own ranking. This also guards against
the "nautisk"/"nautical" false-positive class seen in tools/belgium_kbo_fetch.py
and tools/netherlands_anbi_fetch.py, since "nautisk" contains "autis" too --
excluded explicitly below.

The register's own address fields (forretningsadresse: street, postal code,
city, municipality) are used to build a geocodable address string --
deeper than the Netherlands ANBI register (city-only) since Norway records
full street addresses. Entities under bankruptcy (konkurs) or winding-up
(underAvvikling) are excluded, matching the exclusion logic in
belgium_kbo_fetch.py (struck-off entities) and netherlands_anbi_fetch.py
("in liquidatie").

Also searches "asperger" (part of the autism spectrum, not covered by the
autism-root terms above) and checks each entity's `historiskeNavn`
(historical name) list, not just its current name -- Brreg tracks name
changes per entity, same class of gotcha found in Finland's registry with
auxiliary trade names.

Usage:
    python3 tools/norway_brreg_fetch.py

Writes:
    tools/norway_brreg_scratch/raw_<term>.json   raw API responses (gitignored)
    new_resources_norway.json                     final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "norway_brreg_scratch")
os.makedirs(SCRATCH, exist_ok=True)
OUT_PATH = os.path.join(REPO, "new_resources_norway.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
API = "https://data.brreg.no/enhetsregisteret/api/enheter"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Norway Bronnoysund Register Centre (Enhetsregisteret) - official national entity registry"

SEARCH_TERMS = ["autisme", "autistisk", "autist", "autismeforeningen", "asperger"]
KEEP_SUBSTR = ["autis", "asperger"]
EXCLUDE_SUBSTR = ["nautisk", "nautisch", "dødsbo"]  # "dødsbo" = sole proprietor deceased, estate in probate


def fetch_term(term):
    cache = os.path.join(SCRATCH, f"raw_{term}.json")
    if os.path.exists(cache):
        print(f"  using cached {cache}")
        return json.load(open(cache, encoding="utf-8"))
    params = {"navn": term, "size": 500}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={**HEADERS, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    entities = data.get("_embedded", {}).get("enheter", [])
    json.dump(entities, open(cache, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"  {term}: {len(entities)} raw hits from API")
    return entities


def geocode(address, fallback_city):
    for q in [address, fallback_city]:
        if not q:
            continue
        params = {"q": q, "format": "json", "limit": 1}
        url = NOMINATIM + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                results = json.loads(resp.read())
            if results:
                return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
        except Exception as e:
            print(f"  geocode failed for {q!r}: {e}")
        time.sleep(1.1)
    return None


def main():
    print("Fetching Norway Bronnoysund register...")
    all_entities = {}
    for term in SEARCH_TERMS:
        for e in fetch_term(term):
            all_entities[e["organisasjonsnummer"]] = e
        time.sleep(1.1)
    print(f"  {len(all_entities)} unique entities across all search terms")

    matches = []
    for e in all_entities.values():
        name = e.get("navn", "")
        historical = [h.get("navn", "") for h in (e.get("historiskeNavn") or [])]
        all_names_low = [n.lower() for n in [name] + historical]
        # Check current name AND any historical name (Brreg tracks name-change history per
        # entity, same class of gotcha found in Finland's registry with auxiliary trade names).
        if not any(any(k in n for k in KEEP_SUBSTR) for n in all_names_low):
            continue
        low = name.lower()
        if any(k in low for k in EXCLUDE_SUBSTR):
            continue
        if e.get("konkurs") or e.get("underAvvikling") or e.get("underTvangsavviklingEllerTvangsopplosning"):
            continue
        matches.append(e)
    print(f"  {len(matches)} matches after substring filter + status exclusion")

    resources = []
    for e in matches:
        name = e["navn"].title()
        addr = e.get("forretningsadresse") or {}
        street = ", ".join(addr.get("adresse") or [])
        city = addr.get("poststed")
        postnr = addr.get("postnummer")
        parts = [p for p in [street, postnr, city, "Norway"] if p]
        full_address = ", ".join(parts) if parts else None
        fallback_city = f"{city}, Norway" if city else None

        coords = geocode(full_address, fallback_city)
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec

        orgform = (e.get("organisasjonsform") or {}).get("beskrivelse", "")
        naering = (e.get("naeringskode1") or {}).get("beskrivelse", "")
        activity = " ".join(e.get("aktivitet") or [])
        desc_bits = [b for b in [f"Registered as a {orgform.lower()}" if orgform else None,
                                  f"in {city}, Norway." if city else "in Norway.",
                                  naering if naering else None,
                                  activity if activity else None] if b]
        description = " ".join(desc_bits).strip()
        if not description:
            description = f"Norwegian registered entity, {name}."

        entry = {
            "name": name,
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": description,
        }
        if full_address:
            entry["address"] = full_address
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
