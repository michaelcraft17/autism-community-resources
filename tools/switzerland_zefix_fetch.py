#!/usr/bin/env python3
"""
Swiss autism-related entities from Zefix (Zentraler Firmenindex / Central
Business Names Index), the Swiss Federal Commercial Registry Office's
official national register of every entity in the Swiss commercial
register (companies, associations, foundations):

    https://www.zefix.ch

HANDOFF previously noted Zefix's *documented* public API
(www.zefix.admin.ch/ZefixREST) 401s without a client-registered API key.
That's still true for that host. But the live www.zefix.ch website (the
public search UI everyone actually uses) calls its own, separate,
undocumented, unauthenticated JSON endpoints on a different host:

    POST https://www.zefix.ch/ZefixREST/api/v1/firm/search.json
         {"name": "<term>", "searchType": "exact"}
    GET  https://www.zefix.ch/ZefixREST/api/v1/firm/<ehraid>.json

Both confirmed working with a plain unauthenticated request and a
descriptive User-Agent, same tier of discovery as Belgium's KBO PDF export
or Greece's GEMI publicity API (a real endpoint the public site itself
uses, not an internal/admin one) -- not the same host or code path as the
401'ing admin.ch API, so this isn't evasion of that restriction, it's a
different, genuinely public endpoint.

`searchType: "exact"` is misleadingly named -- it's actually a substring
match on the company name (confirmed: querying "autisme" matches "autisme
suisse romande", a strict superstring). Searching the literal root "autis"
catches all of autisme (French)/autismus (German)/autism (English) in one
query; "autismo" (Italian) and "autistisch"/"autistique"/"autistica" all
returned zero hits separately, so not queried on their own. "asperger" is
queried separately since it doesn't share "autis" as a substring -- same
Asperger-inclusion rationale as Norway/Finland/Slovakia/Bulgaria/France.

Real false positives excluded here by checking each hit's registered
`purpose` text via the detail endpoint, not just trusting the name match
(same discipline as Bulgaria's "АСПЕР" and Norway's "nautisk" exclusions):
- "Autisä GmbH" -- a car-trade business ("Handel mit Autos"), "Autisä"
  coincidentally contains "autis".
- "AUTISM - Passarinho Silva" -- a clothing brand named "AUTISM", not an
  autism-related service.
- "asperger gmbh" -- HR/job-coaching consultancy; purpose text has nothing
  to do with Asperger's, presumably named after a founder's surname
  (Asperger is a real, if uncommon, German-language surname).
Also excluded: entities with status `IN_AUFLOESUNG` (in liquidation/being
wound up) -- same exclusion class as Norway's `konkurs`/`underAvvikling`
and Belgium's struck-off entities -- even when genuinely autism-related in
purpose (two real orgs, "Autisme Gabriel" and "Aspergers at Work GmbH",
were excluded on this basis alone).

Net: 13 active, genuinely autism/Asperger-related Swiss entities kept, out
of 18 raw substring hits.

The detail endpoint returns a full street address (address.street/
houseNumber/swissZipCode/town) -- no separate geocoding-service address
assembly gotcha like Estonia/Bulgaria's hierarchical addresses.

Usage:
    python3 tools/switzerland_zefix_fetch.py

Writes:
    tools/switzerland_zefix_scratch/raw_<term>.json   raw API responses (gitignored)
    new_resources_switzerland.json                     final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "switzerland_zefix_scratch")
os.makedirs(SCRATCH, exist_ok=True)
OUT_PATH = os.path.join(REPO, "new_resources_switzerland.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)",
           "Content-Type": "application/json"}
SEARCH_API = "https://www.zefix.ch/ZefixREST/api/v1/firm/search.json"
DETAIL_API = "https://www.zefix.ch/ZefixREST/api/v1/firm/{}.json"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Switzerland Zefix (Zentraler Firmenindex) - official federal commercial registry"

SEARCH_TERMS = ["autis", "asperger"]
EXCLUDE_EHRAID = {920199, 1413729, 1426120}  # Autisä (car trade), AUTISM clothing brand, asperger gmbh (HR consultancy)


def search_term(term):
    cache = os.path.join(SCRATCH, f"raw_{term}.json")
    if os.path.exists(cache):
        print(f"  using cached {cache}")
        return json.load(open(cache, encoding="utf-8"))
    body = json.dumps({"name": term, "searchType": "exact"}).encode("utf-8")
    req = urllib.request.Request(SEARCH_API, data=body, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    hits = data.get("list", [])
    json.dump(hits, open(cache, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"  {term!r}: {len(hits)} raw hits")
    return hits


def fetch_detail(ehraid):
    req = urllib.request.Request(DETAIL_API.format(ehraid), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


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
    print("Fetching Switzerland Zefix register...")
    all_hits = {}
    for term in SEARCH_TERMS:
        for e in search_term(term):
            all_hits[e["ehraid"]] = e
        time.sleep(1.1)
    print(f"  {len(all_hits)} unique entities across all search terms")

    resources = []
    for ehraid, hit in all_hits.items():
        if ehraid in EXCLUDE_EHRAID:
            continue
        if hit.get("status") == "IN_AUFLOESUNG":
            continue

        detail = fetch_detail(ehraid)
        time.sleep(1.1)

        name = detail["name"].strip()
        purpose = (detail.get("purpose") or "").strip()
        addr = detail.get("address") or {}
        street = f"{addr.get('street', '')} {addr.get('houseNumber', '')}".strip()
        town = addr.get("town")
        zipc = addr.get("swissZipCode")
        parts = [p for p in [street, zipc, town, "Switzerland"] if p]
        full_address = ", ".join(parts) if parts else None
        fallback_city = f"{town}, Switzerland" if town else None

        coords = geocode(full_address, fallback_city)
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec

        description = f"Registered Swiss entity (Zefix): {purpose}" if purpose \
            else f"{name} -- see Zefix (Swiss federal commercial registry) for details."

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
