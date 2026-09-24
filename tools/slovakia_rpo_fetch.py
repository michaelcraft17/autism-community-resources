#!/usr/bin/env python3
"""
Slovak autism-related organizations from RPO (Register právnických
osôb, podnikateľov a orgánov verejnej moci / Register of Legal
Persons, Entrepreneurs and Public Authorities), run by the Statistical
Office of the Slovak Republic -- the current unified master registry
that superseded the older fragmented registers:

    https://rpo.statistics.sk/rpo/rest/search/search/anonym

Free, no API key, no login (the "anonym" in the endpoint name is
literal -- it's the public, unauthenticated search). Found by driving
the live search form at rpo.statistics.sk/new/ once with Playwright
and reading the network log, same technique as Belgium/Slovenia/
Greece. Simple POST body:
`{"query":{"organizationFullName":"<term>","fullTextSearch":[true],
"showHistorical":[true],"showOrganizationUnit":[true]}}`.

Note this is a better source than the one HANDOFF.md previously
documented as a dead end for Slovakia: the open-data catalog
(data.slovensko.sk) dataset "Register neziskových organizácií" points
to `ives.minv.sk`, a legacy portal that returns a consistent 503 --
RPO is a separate, current, working system entirely.

`fullTextSearch: true` matches an organization's stated purpose, not
just its name, so a few hits won't have "autiz-" in the name itself
(e.g. a general disability-support org whose charter mentions autism)
-- kept as-is, same standard as Latvia's/Norway's keyword-in-name
matching, since the API is doing the matching, not a loose substring
guess. Entries with `orgTerminationDate` set are excluded (dissolved).

Also searches "asperger" (part of the autism spectrum, not covered by the
autism-root terms above) -- found a real match, "ASPERGER KLUB".

Only `addrMunicipality` (no street address) is available from search;
geocoded at the municipality level.

Usage:
    python3 tools/slovakia_rpo_fetch.py

Writes:
    tools/slovakia_rpo_scratch/raw_<term>.json   raw API responses (gitignored)
    new_resources_slovakia.json                   final resource-schema output (repo root)
"""
import html
import http.cookiejar
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "slovakia_rpo_scratch")
os.makedirs(SCRATCH, exist_ok=True)
OUT_PATH = os.path.join(REPO, "new_resources_slovakia.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)",
           "Content-Type": "application/json"}
AUTH_URL = "https://rpo.statistics.sk/rpo/rest/auth/user"
API = "https://rpo.statistics.sk/rpo/rest/search/search/anonym"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Slovakia RPO (Register of Legal Persons, Statistical Office) - official national entity registry"

SEARCH_TERMS = ["autizmus", "autisti", "autistick", "autizmom", "asperger"]

# The search endpoint needs a JSESSIONID cookie, minted by POSTing to
# auth/user first -- a plain unauthenticated urllib request 401s otherwise.
_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))


def establish_session():
    req = urllib.request.Request(AUTH_URL, data=b"{}", headers=HEADERS, method="POST")
    _opener.open(req, timeout=20).read()


def fetch_term(term):
    cache = os.path.join(SCRATCH, f"raw_{term}.json")
    if os.path.exists(cache):
        print(f"  using cached {cache}")
        return json.load(open(cache, encoding="utf-8"))
    body = json.dumps({"query": {"organizationFullName": term, "fullTextSearch": [True],
                                  "showHistorical": [True], "showOrganizationUnit": [True]}}).encode("utf-8")
    req = urllib.request.Request(API, data=body, headers=HEADERS, method="POST")
    with _opener.open(req, timeout=30) as resp:
        data = json.load(resp)
    hits = data.get("results", [])
    json.dump(hits, open(cache, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"  {term!r}: {len(hits)} raw hits from API")
    return hits


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
    print("Fetching Slovakia RPO register...")
    establish_session()
    all_hits = {}
    for term in SEARCH_TERMS:
        for h in fetch_term(term):
            if not h.get("orgTerminationDate"):  # excludes dissolved orgs
                all_hits[h["orgIdentifierValue"]] = h
        time.sleep(1.1)
    print(f"  {len(all_hits)} unique active entities across all search terms")

    resources = []
    for h in all_hits.values():
        name = html.unescape(h.get("orgNameFullName", "")).strip()
        municipality = html.unescape(h.get("addrMunicipality", "")).strip()
        address = f"{municipality}, Slovakia" if municipality else "Slovakia"

        coords = geocode(address) if municipality else None
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec

        entry = {
            "name": name,
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": f"Registered organization in the Slovak RPO national registry"
                            + (f", based in {municipality}." if municipality else "."),
            "address": address,
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
