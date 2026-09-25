#!/usr/bin/env python3
"""
French autism-related associations from the RNA (Repertoire National des
Associations) -- France's official government registry of every declared
1901-law association (2.26M total), published as open data under the Etalab
2.0 licence by the Ministry of the Interior:

    https://www.data.gouv.fr/datasets/repertoire-national-des-associations

Queried here via its Opendatasoft-hosted mirror, which (unlike the raw
data.gouv.fr bulk ZIP files) exposes a real search API:

    https://public.opendatasoft.com/api/records/1.0/search/?dataset=ref-france-association-repertoire-national

This is the same tier of source as tools/cqc_uk_fetch.py's UK government CSV
or tools/npi_taxonomy_fetch.py's US registry -- an official structured
dataset, not scraped or LLM-narrated. Every row is a real association the
French government has on file, with a real registered address and, usefully,
a pre-computed geo_point_2d (no separate geocoding pass needed here, unlike
the Autism-Europe PDF tools).

Query terms: "autisme" (2077 hits), "autiste" (1358), "autistes" (1184) return
meaningfully different result sets -- the API does not stem across these
forms -- so this fetches the OR-combined query (2801 hits) rather than any
one term alone. Filters to `position == "Active"` only (skips "Dissoute" --
legally dissolved associations still on file). The RNA does not publish
websites/phone numbers (privacy-scoped registration data), so entries have no
`website` field -- expected and fine, matches other placeless-tolerant
entries already in the dataset.

Expanded 2026-09-25 with an "asperger" Asperger-sweep term (same rationale as
Norway/Finland/Slovakia/Bulgaria: Asperger's is part of the autism spectrum
but wasn't covered by the autisme/autiste/autistes root). "asperger" alone
returns 111 hits; 21 are net-new active associations not already matched by
the autism-root terms (real dedicated orgs like "ASPERGER VOSGES," "ASPERGER
ACCUEIL," "APIPA-ASPERGER-TSA," plus some the API's own relevance ranking
pulled in that only mention Asperger's in passing -- kept as-is, same
tolerance as the autism-root query's own false-positive rate).

Known upstream data quality issue: ~37% of `object` (description) fields for
older records (pre-2009 declarations, part of the "RNA_import" legacy batch)
have specific accented characters corrupted (e.g. "acces" renders as
"accÚs") -- confirmed present in the raw API response itself, not introduced
by this script. Names, addresses, and coordinates are unaffected. Not
auto-repaired here (no reliable single encoding transform fixes it; it's a
historical data-entry/migration artifact in the government's own database)
-- flagged as-is, same spirit as the site tolerating other imperfect fields.

Usage:
    python3 tools/france_rna_fetch.py

Writes:
    tools/france_rna_scratch/raw_records.json   raw fetched records (gitignored)
    new_resources_france_rna.json                final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "france_rna_scratch")
os.makedirs(SCRATCH, exist_ok=True)
RAW_PATH = os.path.join(SCRATCH, "raw_records.json")
OUT_PATH = os.path.join(REPO, "new_resources_france_rna.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
API = "https://public.opendatasoft.com/api/records/1.0/search/"
DATASET = "ref-france-association-repertoire-national"
QUERY = "autisme OR autiste OR autistes OR asperger"
PAGE_SIZE = 1000

SOURCE = "France RNA (Repertoire National des Associations) - official government open data, data.gouv.fr"

TYPE_KEYWORDS = [
    (("recherche", "etude", "scientifique"), "medical"),
    (("therapie", "soin", "clinique", "medical", "reeducation", "psycho"), "medical"),
    (("ecole", "scolaire", "formation", "education", "pedagog"), "education"),
    (("droit", "plaidoyer", "defense", "politique"), "advocacy"),
    (("loisir", "sport", "vacances", "voile", "equitation", "sortie"), "social"),
]


def infer_type(object_text):
    t = (object_text or "").lower()
    for keywords, kind in TYPE_KEYWORDS:
        if any(k in t for k in keywords):
            return kind
    return "general_support"


def fetch_page(start):
    params = {"dataset": DATASET, "q": QUERY, "rows": PAGE_SIZE, "start": start}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_all():
    records = []
    start = 0
    total = None
    while total is None or start < total:
        data = fetch_page(start)
        total = data["nhits"]
        batch = data.get("records", [])
        records.extend(batch)
        print(f"  fetched {len(records)}/{total}")
        start += PAGE_SIZE
        time.sleep(1)
    return records


def build_address(f):
    parts = []
    if f.get("street_number_asso") or f.get("street_name_asso"):
        parts.append(f"{f.get('street_number_asso', '')} {f.get('street_name_asso', '')}".strip())
    if f.get("pc_address_asso") or f.get("com_name_asso"):
        parts.append(f"{f.get('pc_address_asso', '')} {f.get('com_name_asso', '')}".strip())
    parts.append("France")
    return ", ".join(p for p in parts if p)


def build_resources(records):
    resources = []
    seen_ids = set()
    for r in records:
        f = r["fields"]
        if f.get("position") != "Active":
            continue
        rid = f.get("id") or r.get("recordid")
        if rid in seen_ids:
            continue
        seen_ids.add(rid)

        title = f.get("title") or f.get("short_title")
        if not title:
            continue
        object_text = f.get("object", "")
        coord = f.get("geo_point_2d")

        entry = {
            "name": title.strip().title(),
            "address": build_address(f),
            "type": infer_type(object_text),
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": f"French officially registered association (RNA): {object_text.strip()}." if object_text
            else f"{title.strip().title()} -- see the RNA (French association registry) for details.",
        }
        if coord and len(coord) == 2:
            entry["coordinates"] = {"lat": coord[0], "lng": coord[1]}
        else:
            entry["placeless"] = True
        resources.append(entry)
    return resources


def main():
    print(f"Fetching RNA records matching '{QUERY}'...")
    records = fetch_all()
    with open(RAW_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)

    resources = build_resources(records)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nFetched {len(records)} raw records, {len(resources)} active+unique after filtering")
    print(f"Wrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} have coordinates")


if __name__ == "__main__":
    main()
