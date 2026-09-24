#!/usr/bin/env python3
"""
Greek autism-related organizations from GEMI (Γενικό Εμπορικό Μητρώο /
General Commercial Registry), Greece's official national business
registry, via its public "Publicity" search portal:

    https://publicity.businessportal.gr

Free, no API key, no login. Two plain JSON endpoints, found by driving
the live search UI once with Playwright and reading the network log
(the same technique used for Belgium's KBO and Slovenia's AJPES):

  - `POST /api/autocomplete/<url-encoded term>` -- name search, returns
    id/arGemi/title/company name/status per match.
  - `POST /api/company/details` with body
    `{"query":{"arGEMI":"<id>"},"token":null,"language":"el"}` -- full
    detail record including a real street address (`company_address`).
    The page's HTML preloads a reCAPTCHA script, which looked like it
    might gate this, but `"token":null` works fine in practice -- no
    challenge was ever triggered fetching these public records.

A plain, no-UA request gets a transient 429 the very first time (seen
once during discovery, not since) -- a descriptive User-Agent is set
here regardless, consistent with every other fetcher in this project.

Only "Ενεργή" (active) status entries are kept; "Διαγραφή" (struck
off) and other inactive statuses are excluded.

Usage:
    python3 tools/greece_gemi_fetch.py

Writes:
    tools/greece_gemi_scratch/raw_<term>.json   raw API responses (gitignored)
    new_resources_greece.json                    final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "greece_gemi_scratch")
os.makedirs(SCRATCH, exist_ok=True)
OUT_PATH = os.path.join(REPO, "new_resources_greece.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)",
           "Content-Type": "application/json"}
AUTOCOMPLETE_API = "https://publicity.businessportal.gr/api/autocomplete/"
DETAILS_API = "https://publicity.businessportal.gr/api/company/details"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Greece GEMI (General Commercial Registry) - official national business registry"

SEARCH_TERMS = ["αυτισμ", "αυτιστικ"]
ACTIVE_STATUS = "Ενεργή"


def fetch_term(term):
    safe = urllib.parse.quote(term, safe="")
    cache = os.path.join(SCRATCH, f"raw_{safe}.json")
    if os.path.exists(cache):
        print(f"  using cached {cache}")
        return json.load(open(cache, encoding="utf-8"))
    url = AUTOCOMPLETE_API + urllib.parse.quote(term)
    req = urllib.request.Request(url, data=b"{}", headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    hits = data.get("payload", {}).get("autocomplete", [])
    json.dump(hits, open(cache, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"  {term!r}: {len(hits)} raw hits from API")
    return hits


def fetch_details(ar_gemi):
    body = json.dumps({"query": {"arGEMI": str(ar_gemi)}, "token": None, "language": "el"}).encode("utf-8")
    req = urllib.request.Request(DETAILS_API, data=body, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        return data.get("companyInfo", {}).get("payload", {}).get("company")
    except Exception as e:
        print(f"  details fetch failed for {ar_gemi}: {e}")
        return None


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
    print("Fetching Greece GEMI registry...")
    all_hits = {}
    for term in SEARCH_TERMS:
        for h in fetch_term(term):
            if h.get("companyStatus") == ACTIVE_STATUS:
                all_hits[h["arGemi"]] = h
        time.sleep(1.1)
    print(f"  {len(all_hits)} unique active entities across all search terms")

    resources = []
    for ar_gemi, hit in all_hits.items():
        details = fetch_details(ar_gemi)
        time.sleep(1.1)
        if not details:
            continue
        name = details.get("name") or hit.get("co_name") or hit.get("title")
        addr = details.get("company_address_map") or details.get("company_address")
        full_address = f"{addr}, Greece" if addr else "Greece"

        coords = geocode(full_address) if addr else None
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec

        entry = {
            "name": name.strip(),
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": "Registered organization in Greece's GEMI national business registry.",
            "address": full_address,
        }
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        resources.append(entry)
        print(f"  {name}: {'geocoded' if coords else 'placeless'}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} geocoded")


if __name__ == "__main__":
    main()
