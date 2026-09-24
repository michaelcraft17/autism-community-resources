#!/usr/bin/env python3
"""
Finnish autism-related organizations from PRH (Patentti- ja rekisterihallitus,
the Finnish Patent and Registration Office)'s official open Business
Information System API (YTJ):

    https://avoindata.prh.fi/opendata-ytj-api/v3/companies?name=<term>

Free, no API key. Covers every registered Finnish business, association, and
foundation -- same tier of source as tools/norway_brreg_fetch.py's
Bronnoysund register.

Small country, small yield: querying literal Finnish autism-root terms
(autismi, autismisäätiö, autismiyhdistys) surfaces only a handful of real
matches once closed/superseded entities are excluded -- Finland doesn't
appear to have Norway's pattern of dozens of regional chapters registered
as separate legal entities. As with tools/norway_brreg_fetch.py, the API's
name search is approximate (querying the bare substring "autis" also
returns unrelated boating-industry entities like "Ky Nautisale Kb" and
"NautiSaimaa Oy", since "nautis-" contains "autis" too) -- filtered out
client-side, same false-positive class documented in
tools/belgium_kbo_fetch.py and tools/netherlands_anbi_fetch.py.

Entities whose current registration has an endDate (dissolved, merged, or
renamed into a successor already covered by a live query) are excluded.

Usage:
    python3 tools/finland_ytj_fetch.py

Writes:
    tools/finland_ytj_scratch/raw_<term>.json   raw API responses (gitignored)
    new_resources_finland.json                   final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "finland_ytj_scratch")
os.makedirs(SCRATCH, exist_ok=True)
OUT_PATH = os.path.join(REPO, "new_resources_finland.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
API = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Finland PRH Business Information System (YTJ) - official national entity registry"

SEARCH_TERMS = ["autismi", "autismisäätiö", "autismiyhdistys", "autismikirjo"]
KEEP_SUBSTR = ["autis"]
EXCLUDE_SUBSTR = ["nautis"]
# real-estate holding subsidiary of the Autism Foundation, not itself a
# service-providing resource
EXCLUDE_NAMES = ["autismisäätiön kiinteistöt"]


def fetch_term(term):
    safe = term.replace("ä", "a").replace("ö", "o")
    cache = os.path.join(SCRATCH, f"raw_{safe}.json")
    if os.path.exists(cache):
        print(f"  using cached {cache}")
        return json.load(open(cache, encoding="utf-8"))
    params = {"name": term}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={**HEADERS, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    companies = data.get("companies", [])
    json.dump(companies, open(cache, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"  {term}: {len(companies)} raw hits from API")
    return companies


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
    print("Fetching Finland YTJ register...")
    all_companies = {}
    for term in SEARCH_TERMS:
        for c in fetch_term(term):
            all_companies[c["businessId"]["value"]] = c
        time.sleep(1.1)
    print(f"  {len(all_companies)} unique entities across all search terms")

    matches = []
    for c in all_companies.values():
        names = c.get("names") or []
        if not names:
            continue
        current = names[0]
        name = current.get("name", "")
        low = name.lower()
        if not any(k in low for k in KEEP_SUBSTR):
            continue
        if any(k in low for k in EXCLUDE_SUBSTR):
            continue
        if any(k in low for k in EXCLUDE_NAMES):
            continue
        if current.get("endDate"):
            continue  # this name/entity has ended -- dissolved, merged, or renamed
        matches.append((name, c))
    print(f"  {len(matches)} matches after substring filter + status exclusion")

    resources = []
    for name, c in matches:
        addrs = c.get("addresses") or []
        street_addr = next((a for a in addrs if a.get("type") == 1), addrs[0] if addrs else None)
        city = None
        full_address = None
        if street_addr:
            offices = street_addr.get("postOffices") or []
            city = next((o["city"] for o in offices if o.get("languageCode") == "1"), offices[0]["city"] if offices else None)
            parts = [
                f"{street_addr.get('street','')} {street_addr.get('buildingNumber','')}".strip(),
                street_addr.get("postCode"),
                city,
                "Finland",
            ]
            full_address = ", ".join(p for p in parts if p)
        fallback_city = f"{city}, Finland" if city else None

        coords = geocode(full_address, fallback_city)
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec

        forms = c.get("companyForms") or []
        form_desc = next((d["description"] for d in (forms[0].get("descriptions") or []) if d.get("languageCode") == "3"), "") if forms else ""
        line = c.get("mainBusinessLine") or {}
        line_desc = next((d["description"] for d in (line.get("descriptions") or []) if d.get("languageCode") == "3"), "")
        desc_bits = [b for b in [
            f"Registered as a {form_desc.lower()}" if form_desc else "Registered entity",
            f"in {city}, Finland." if city else "in Finland.",
            line_desc + "." if line_desc else None,
        ] if b]
        description = " ".join(desc_bits).strip()

        entry = {
            "name": name.strip(),
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": description,
        }
        website = (c.get("website") or {}).get("url")
        if website:
            if not website.startswith("http"):
                website = "https://" + website
            entry["website"] = website
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
