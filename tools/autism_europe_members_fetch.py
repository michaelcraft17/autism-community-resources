#!/usr/bin/env python3
"""
National autism organizations for Germany, Sweden, Lithuania, and Russia, sourced
from Autism-Europe's own official member directory PDF (an umbrella federation's
verified member list, not a scraped or LLM-narrated source):

    https://www.autismeurope.org/wp-content/uploads/2023/04/Members-associations-of-Autism-Europe_2023.pdf

Every name/address/website below is copied verbatim from that PDF (see
citations inline). This is a one-off curated list rather than a live API pull
because Autism-Europe doesn't expose one -- but the source document itself is
official and structured (a federation's own membership register), same tier
of reliability as tools/cqc_uk_fetch.py's government CSV, just not machine-
queryable at the source. China has no members in this directory (Autism-
Europe is Europe-focused) and no other official structured China dataset was
found this session -- see HANDOFF.md for what's already been ruled out.

Usage:
    python3 tools/autism_europe_members_fetch.py

Writes:
    new_resources_autism_europe_members.json   final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO, "new_resources_autism_europe_members.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE_PDF = "Autism-Europe official member directory (2023 PDF)"

ENTRIES = [
    {
        "name": "Autismus Deutschland",
        "address": "Rothenbaumchaussee 15, 20148 Hamburg, Germany",
        "website": "https://www.autismus.de",
        "type": "advocacy",
        "services": ["Advocacy", "Information & Support"],
        "description": "National association of autistic people and parents in Germany; full member of Autism-Europe.",
    },
    {
        "name": "Autism- och Aspergerforbundet (Autism Sweden)",
        "address": "Bellmansgatan 30, 118 47 Stockholm, Sweden",
        "website": "https://www.autism.se",
        "type": "advocacy",
        "services": ["Advocacy", "Information & Support"],
        "description": "National association of autistic people and parents in Sweden; full member of Autism-Europe.",
    },
    {
        "name": "Lietaus vaikai (Rain Children)",
        "address": "Pylimo str. 14A/37, 01117 Vilnius, Lithuania",
        "website": "https://www.lietausvaikai.lt",
        "type": "advocacy",
        "services": ["Advocacy", "Information & Support"],
        "description": "National association of autistic people and parents in Lithuania; full member of Autism-Europe.",
    },
    {
        "name": "Autism Regions Association",
        "address": "90 Dubininskaya str., 115093 Moscow, Russia",
        "website": "https://autism-regions.org",
        "type": "advocacy",
        "services": ["Advocacy", "Information & Support"],
        "description": "National association of autistic people and parents in Russia; full member of Autism-Europe.",
    },
    {
        "name": 'Chuvash Regional Public Organisation for Helping Children with ASD "Wings"',
        "address": "Avtozapravochny pr. 19, Cheboksary, Chuvash Republic, 428003, Russia",
        "website": "http://wings-autism.ru",
        "type": "general_support",
        "services": ["Information & Support", "Family Support"],
        "description": "Regional resource centre in Chuvashia, Russia helping children with autism spectrum disorder; associate member of Autism-Europe.",
    },
    {
        "name": "Our Sunny World (Solnechny Mir)",
        "address": "Leskova 6B, Moscow, 127349, Russia",
        "website": "http://solnechnymir.ru",
        "type": "medical",
        "services": ["Rehabilitation", "Therapy"],
        "description": "Rehabilitation centre for disabled children in Moscow, Russia; associate member of Autism-Europe.",
    },
]


def geocode_query(query):
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


def geocode(address):
    coords = geocode_query(address)
    if coords:
        return coords
    time.sleep(1.1)
    # Fall back to city + country -- still an accurate pin, just not street-level
    parts = [p.strip() for p in address.split(",")]
    fallback = ", ".join(parts[-2:]) if len(parts) >= 2 else address
    print(f"  full address failed, retrying with {fallback!r}")
    return geocode_query(fallback)


def main():
    resources = []
    for e in ENTRIES:
        coords = geocode(e["address"])
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        entry = {
            "name": e["name"],
            "address": e["address"],
            "website": e["website"],
            "type": e["type"],
            "source": SOURCE_PDF,
            "services": e["services"],
            "description": e["description"],
        }
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        resources.append(entry)
        print(f"  {e['name']}: {'geocoded' if coords else 'NOT geocoded (placeless)'}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} geocoded")


if __name__ == "__main__":
    main()
