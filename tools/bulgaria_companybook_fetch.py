#!/usr/bin/env python3
"""
Bulgarian autism-related organizations via CompanyBook.bg's free API
(https://companybook.bg/api-docs), a third party that republishes
Bulgaria's official Commercial Register / Register of Non-Profit
Legal Entities data. Its own FAQ states the data "comes from the
daily publications of the Registry Agency, uploaded to the [Ministry
of e-Governance] open data website... under the CC-BY license" --
i.e. it's official government open data, not scraped.

Why a third party at all: Bulgaria's own open-data portal
(data.egov.bg) returns a 403 even for Googlebot/Bingbot (confirmed via
an independent source, not just this project's sandbox -- a real
site-wide restriction), and the Registry Agency's own portal
(portal.registryagency.bg) has no free entity-name search -- its only
apparently-free search box actually searches the portal's own help
content, and its real company-verification tool requires an OAuth
login. See HANDOFF.md's "Ruled out" section for the full trail.

Requires a free API key (COMPANYBOOK_API_KEY env var, never hardcoded
or committed) -- sign up at https://companybook.bg/sign-up. Free tier
is 100 requests/day, which comfortably covers this script's usage
(a handful of search terms, plus one detail call per match).

Two endpoints used:
  - GET /api/v2/companies/search?name=<term>&status=true -- name
    search, status=true restricts to active entities (registry status
    "N" = active; "L" = liquidated/struck off).
  - GET /api/companies/{uic}?with_data=true -- full record for one
    match, including a real structured address (`seat`).

Usage:
    COMPANYBOOK_API_KEY=<your key> python3 tools/bulgaria_companybook_fetch.py

Writes:
    tools/bulgaria_companybook_scratch/raw_<term>.json   raw search responses (gitignored)
    new_resources_bulgaria.json                           final resource-schema output (repo root)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "bulgaria_companybook_scratch")
os.makedirs(SCRATCH, exist_ok=True)
OUT_PATH = os.path.join(REPO, "new_resources_bulgaria.json")

API_KEY = os.environ.get("COMPANYBOOK_API_KEY")
HEADERS_BASE = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
SEARCH_API = "https://api.companybook.bg/api/v2/companies/search"
DETAIL_API = "https://api.companybook.bg/api/companies/{uic}"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = ("Bulgaria Commercial Register / Register of Non-Profit Legal Entities, via "
          "CompanyBook.bg (republishes official Registry Agency CC-BY open data)")

SEARCH_TERMS = ["аутизъм", "аутизмa", "аутистич"]


def api_get(url):
    req = urllib.request.Request(url, headers={**HEADERS_BASE, "X-API-Key": API_KEY})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_term(term):
    cache = os.path.join(SCRATCH, f"raw_{term}.json")
    if os.path.exists(cache):
        print(f"  using cached {cache}")
        return json.load(open(cache, encoding="utf-8"))
    params = {"name": term, "status": "true"}
    url = SEARCH_API + "?" + urllib.parse.urlencode(params)
    data = api_get(url)
    hits = data.get("results", [])
    json.dump(hits, open(cache, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"  {term!r}: {len(hits)} raw hits from API")
    return hits


def fetch_detail(uic):
    url = DETAIL_API.format(uic=uic) + "?with_data=true"
    try:
        data = api_get(url)
        return data.get("company")
    except Exception as e:
        print(f"  detail fetch failed for {uic}: {e}")
        return None


def _geocode_one(q):
    params = {"q": q, "format": "json", "limit": 1}
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS_BASE)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.loads(resp.read())
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception as e:
        print(f"  geocode failed for {q!r}: {e}")
    return None


def geocode(full_address, settlement):
    # The full street-level address (with "ул." abbreviations etc.) routinely
    # fails to resolve in Nominatim, same issue seen with Estonia's registry
    # addresses -- fall back to "<settlement>, Bulgaria" if so. The settlement
    # field itself carries a "гр."/"с." (town/village) type prefix that also
    # breaks Nominatim (e.g. "гр. Панагюрище" resolves to nothing, but plain
    # "Панагюрище" resolves fine) -- stripped here.
    clean_settlement = None
    if settlement:
        clean_settlement = settlement
        for prefix in ("гр. ", "с. ", "гр.", "с."):
            if clean_settlement.startswith(prefix):
                clean_settlement = clean_settlement[len(prefix):].strip()
                break
    for q in [full_address, f"{clean_settlement}, Bulgaria" if clean_settlement else None]:
        if not q:
            continue
        coords = _geocode_one(q)
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        if coords:
            return coords
    return None


def main():
    if not API_KEY:
        print("ERROR: set COMPANYBOOK_API_KEY (a free key from https://companybook.bg/sign-up)")
        sys.exit(1)

    print("Fetching Bulgaria Commercial/NPO register via CompanyBook.bg...")
    all_hits = {}
    for term in SEARCH_TERMS:
        for h in fetch_term(term):
            if h.get("status") == "N":  # N = active; L = liquidated
                all_hits[h["uic"]] = h
        time.sleep(1.1)
    print(f"  {len(all_hits)} unique active entities across all search terms")

    resources = []
    for uic, hit in all_hits.items():
        detail = fetch_detail(uic)
        time.sleep(1.1)
        if not detail:
            continue
        name = (detail.get("companyName") or {}).get("name") or hit.get("name")
        seat = detail.get("seat") or {}
        addr_parts = [
            f"{seat.get('street','')} {seat.get('streetNumber','')}".strip(),
            seat.get("settlement"),
            seat.get("postCode"),
            "Bulgaria",
        ]
        full_address = ", ".join(p for p in addr_parts if p) or "Bulgaria"

        coords = geocode(full_address, seat.get("settlement"))

        entry = {
            "name": name.strip(),
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": "Registered legal entity in Bulgaria's Commercial Register / "
                            "Register of Non-Profit Legal Entities.",
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
