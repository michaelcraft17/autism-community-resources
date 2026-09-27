#!/usr/bin/env python3
"""
Estonian autism-related organizations from the e-Business Register
(Ariregister) -- run by RIK (Centre of Registers and Information
Systems), Estonia's official register of every company, foundation,
and nonprofit association in the country:

    https://ariregister.rik.ee/est/api/autocomplete?q=<term>

Free, no API key. A plain request with no User-Agent header gets a
403 from this endpoint (a basic bot filter, not a real anti-bot
product) -- fixed by setting a descriptive User-Agent, same as every
other fetcher in this project.

Estonia is a small country (~1.3M people) but has unusually deep,
clean autism-org coverage for its size: querying "autism" alone
surfaces 8 real active organizations (national federation, regional
associations, a foundation, and specialist centers), no false
positives.

Disability-master pass: added general-disability terms (puue/puuetega,
invaliid, erivajadus, kurtide, pimeda, downi). Real, genuine
linguistic-collision false positives found and excluded (see
EXCLUDE_NAMES) -- worth knowing about for any future Estonian-language
term list: "puude" is the genitive of both "puue" (disability) AND
"puu" (tree), so it also matches tree-care/landscaping companies;
"pime" means both "dark" and "blind" in Estonian, matching a film
festival ("Pimedate Ööde Filmifestival" = Dark Nights Film Festival)
and an entertainment company ("Peitus Pimedas" = Hide in the Dark);
and "Invaliidi tn" (Invalid Street) is a real Tallinn street name, so
"invaliid" also matches apartment-building housing co-ops with no
disability connection at all. Deaf ("kurtide") and blind ("pimedate",
minus the two false positives above) national/regional associations
and sports clubs, special-needs ("erivajadus") support centers and a
therapeutic riding club, and both Estonian Down Syndrome organizations
all came back clean.

A follow-up pass found the original term list was too narrow: it missed
other Estonian grammatical forms of "autist" (person with autism) --
"autistide" (genitive/partitive) turned up two more real, active
organizations including the actual national federation ("Eesti Autistide
Liit," which the original "autism"/"autismi" terms missed entirely
despite it being the umbrella body), and "autist" alone (which the API
matches as a fuzzy/broad prefix) turned up "Sihtasutus AUTISTIKA," a real
day center for autistic adults. One ambiguous match, "Autist OÜ" (a
private limited company with no corroborating evidence of being autism-
related, unlike the confirmed MTÜ/foundation matches), is excluded --
same discipline as excluding Bulgaria's "АСПЕР" false positive.

Usage:
    python3 tools/estonia_ariregister_fetch.py

Writes:
    tools/estonia_ariregister_scratch/raw_<term>.json   raw API responses (gitignored)
    new_resources_estonia.json                           final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "estonia_ariregister_scratch")
os.makedirs(SCRATCH, exist_ok=True)
OUT_PATH = os.path.join(REPO, "new_resources_estonia.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
API = "https://ariregister.rik.ee/est/api/autocomplete"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Estonia e-Business Register (Ariregister, RIK) - official national entity registry"

SEARCH_TERMS = ["autism", "autismi", "autistlik", "autist", "autistide"]
# Disability-master pass: general-disability/neurodevelopmental Estonian term
# roots (puue = disability noun stem; invaliid = older but still-used
# "disabled person" term, common in legacy org names; erivajadus = special
# needs; kurt/pime = deaf/blind; down = Down syndrome).
DISABILITY_TERMS = ["puude", "puuetega", "invaliid", "erivajadus", "kurtide", "pimeda", "downi"]
AUTISM_SUBSTR = ["autis"]
DOWN_SYNDROME_SUBSTR = ["downi"]
EXCLUDE_NAMES = [
    "autist oü",  # ambiguous, no corroborating evidence -- see docstring
    # Real linguistic collisions surfaced by the disability-term pass, see docstring:
    "puude hooldus oü", "puudel kõrghaljastus oü", "oü puuder", "a&t puude oü",  # "puude"="of trees" here, not disability
    "tallinn, invaliidi tn 3 korteriühistu", "tallinn, invaliidi tn 4 korteriühistu",  # street name, not disability
    "mittetulundusühing pimedate ööde filmifestival", "peitus pimedas oü",  # "pime"="dark" here, not "blind"
]


def fetch_term(term):
    cache = os.path.join(SCRATCH, f"raw_{term}.json")
    if os.path.exists(cache):
        print(f"  using cached {cache}")
        return json.load(open(cache, encoding="utf-8"))
    params = {"q": term}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    entities = data.get("data", [])
    json.dump(entities, open(cache, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"  {term}: {len(entities)} raw hits from API")
    return entities


def _geocode_one(q):
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
    return None


def geocode(address):
    # Estonian legal addresses ("<county> maakond, <city/parish>, <district/village>
    # linnaosa|küla, <street>") are too granular for Nominatim's parser as one string.
    # Try the full address first, then progressively drop the most specific
    # (rightmost) segment until only "<county/city area>, Estonia" is left.
    parts = [p.strip() for p in address.split(",")]
    for n in range(len(parts), 1, -1):
        coords = _geocode_one(", ".join(parts[:n]))
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        if coords:
            return coords
    return None


def main():
    print("Fetching Estonia e-Business Register...")
    all_entities = {}
    matched_terms = {}
    for term in SEARCH_TERMS + DISABILITY_TERMS:
        for e in fetch_term(term):
            if e.get("status") != "R":  # "Registrisse kantud" - actively registered, not dissolved
                continue
            if (e.get("name") or "").strip().lower() in EXCLUDE_NAMES:
                continue
            all_entities[e["reg_code"]] = e
            matched_terms.setdefault(e["reg_code"], set()).add(term)
        time.sleep(1.1)
    print(f"  {len(all_entities)} unique active entities across all search terms")

    resources = []
    for e in all_entities.values():
        name = e.get("name", "").strip()
        low = name.lower()
        if any(t in low for t in AUTISM_SUBSTR):
            scope = None
        elif any(t in low for t in DOWN_SYNDROME_SUBSTR):
            scope = "neurodevelopmental"
        else:
            scope = "general"
        addr = e.get("legal_address", "")
        zip_code = e.get("zip_code", "")
        full_address = ", ".join(p for p in [addr, zip_code, "Estonia"] if p)

        coords = geocode(full_address)
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec

        entry = {
            "name": name,
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": f"Registered organization in the Estonian e-Business Register.",
            "address": full_address,
            "breadth": "core",
        }
        if scope:
            entry["disability_scope"] = scope
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
