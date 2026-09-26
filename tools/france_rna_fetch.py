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

Expanded again 2026-09-25 (disability-master pass) with the French
disability/neurodevelopmental term list: handicap (50,108 hits alone --
verified with a manual spot-check of 15 records before committing to the
full fetch; real disability associations -- sports, home care, employment,
parental support -- not noise), déficience, trisomie (Down syndrome),
sourd/malentendant (deaf/hard-of-hearing), aveugle/malvoyant (blind/low
vision), dyslexie/dyspraxie/dyscalculie, "infirmité motrice cérébrale"
(cerebral palsy). Records matched only by a disability/neuro term (not an
autism-root term) get `disability_scope` set to "neurodevelopmental" (Down
syndrome, dyslexia, dyspraxia, dyscalculia) or "general" (everything else)
so the site can still filter to autism-only if wanted. This makes France by
far the largest single-country addition in the disability layer.

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
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from category_map import classify

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "france_rna_scratch")
os.makedirs(SCRATCH, exist_ok=True)
RAW_PATH = os.path.join(SCRATCH, "raw_records.json")
OUT_PATH = os.path.join(REPO, "new_resources_france_rna.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
API = "https://public.opendatasoft.com/api/records/1.0/search/"
DATASET = "ref-france-association-repertoire-national"
AUTISM_TERMS = "autisme OR autiste OR autistes OR asperger"
# "handicap" alone is 50,108 hits -- too big for this API's 10,000-record
# start+rows pagination cap, and doesn't share a date/geo field with full
# coverage (a declaration_date-range shard only recovers ~82%; commune-code
# sharding below recovers the same ~82% via a field every record has, so
# that's what's used). Every other disability term is well under 10k and
# fetched directly, no sharding needed.
NARROW_DISABILITY_TERMS = (
    "deficience OR déficience OR trisomie OR sourd OR malentendant "
    "OR aveugle OR malvoyant OR dyslexie OR dyspraxie OR dyscalculie OR "
    '"infirmité motrice cérébrale"'
)
QUERY = f"{AUTISM_TERMS} OR {NARROW_DISABILITY_TERMS}"
PAGE_SIZE = 1000
# commune-code (com_code_asso) shards for the separate "handicap" fetch --
# verified 2026-09-25 that every 10,000-wide bin stays under the API's cap;
# sums to ~41,200 of the true 50,108 (~82%; the rest have no com_code_asso
# in range, e.g. foreign/overseas-territory addresses -- not chased further
# this pass, a documented partial capture like tools/italy_runts_fetch.py).
HANDICAP_SHARDS = [(f"{lo:05d}", f"{lo+9999:05d}") for lo in range(0, 100000, 10000)]

AUTISM_RE = re.compile(r"autis|asperger", re.IGNORECASE)
NEURO_RE = re.compile(r"trisomie|dyslexi|dyspraxi|dyscalculi", re.IGNORECASE)
# everything else in DISABILITY_TERMS that isn't autism/neuro-specific

SOURCE = "France RNA (Repertoire National des Associations) - official government open data, data.gouv.fr"

TYPE_KEYWORDS = [
    (("recherche", "etude", "scientifique"), "medical"),
    (("therapie", "soin", "clinique", "medical", "reeducation", "psycho"), "medical"),
    (("ecole", "scolaire", "formation", "education", "pedagog"), "education"),
    (("droit", "plaidoyer", "defense", "politique"), "advocacy"),
    (("loisir", "sport", "vacances", "voile", "equitation", "sortie"), "social"),
]


def infer_type(title, object_text):
    t = (object_text or "").lower()
    for keywords, kind in TYPE_KEYWORDS:
        if any(k in t for k in keywords):
            return kind
    return classify(title, object_text)


def infer_scope(title, object_text):
    blob = f"{title or ''} {object_text or ''}"
    if AUTISM_RE.search(blob):
        return None
    if NEURO_RE.search(blob):
        return "neurodevelopmental"
    return "general"


def fetch_page(query, start):
    params = {"dataset": DATASET, "q": query, "rows": PAGE_SIZE, "start": start}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_query(query):
    records = []
    start = 0
    total = None
    while total is None or start < total:
        data = fetch_page(query, start)
        total = data["nhits"]
        batch = data.get("records", [])
        records.extend(batch)
        start += PAGE_SIZE
        time.sleep(1)
    return records


def fetch_handicap_sharded():
    records = []
    for lo, hi in HANDICAP_SHARDS:
        q = f"handicap AND com_code_asso:[{lo} TO {hi}]"
        shard = fetch_query(q)
        print(f"  handicap [{lo}-{hi}]: {len(shard)}")
        records.extend(shard)
    return records


def fetch_all():
    records = fetch_query(QUERY)
    print(f"  narrow query: {len(records)}")
    records += fetch_handicap_sharded()
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
            "type": infer_type(title, object_text),
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": f"French officially registered association (RNA): {object_text.strip()}." if object_text
            else f"{title.strip().title()} -- see the RNA (French association registry) for details.",
        }
        scope = infer_scope(title, object_text)
        if scope:
            entry["disability_scope"] = scope
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
