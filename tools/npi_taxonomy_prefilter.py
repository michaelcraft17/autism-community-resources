"""
Step 2 of 4 — run after npi_taxonomy_fetch.py, before npi_taxonomy_geocode.py.

Caps each taxonomy's raw candidates to PER_TAXONOMY_CAP *unique addresses* (deduping
against both each other and community_resources.json) before the slow geocoding step.
Geocoding is the bottleneck (Census's bulk geocoder + Nominatim fallback), so this
avoids spending that time on entries that npi_taxonomy_merge.py's own cap+dedup would
throw away anyway. Overwrites npi_scratch/candidates.jsonl in place; the untouched raw
version is saved to npi_scratch/candidates_raw_full.jsonl first.
"""
import json, os, re
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "npi_scratch")
JSON_FILE = os.path.join(REPO, "community_resources.json")
CANDIDATES_PATH = os.path.join(SCRATCH, "candidates.jsonl")
CAP = 3000  # keep in sync with PER_TAXONOMY_CAP in npi_taxonomy_merge.py

def addr_key(addr):
    street = addr.split(",")[0]
    street = re.sub(r'\s*(STE|SUITE|UNIT|#)\s*\S+$', '', street.upper()).strip()
    rest = ",".join(addr.split(",")[1:])
    return re.sub(r'\s+', ' ', (street + "|" + rest).upper()).strip()

existing = json.load(open(JSON_FILE, encoding="utf-8"))
existing_names = {e["name"].strip().lower() for e in existing}
existing_npis = {e.get("npi_number") for e in existing if e.get("npi_number")}
existing_addr_type = {(addr_key(e["address"]), e.get("type")) for e in existing if e.get("address")}

by_tax = defaultdict(list)
raw_total = 0
with open(CANDIDATES_PATH, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line: continue
        e = json.loads(line)
        raw_total += 1
        by_tax[e.get("services", ["?"])[0]].append(e)

seen_addr_type = set(existing_addr_type)
seen_npi = set()
kept = []
for tax, items in by_tax.items():
    count = 0
    for e in items:
        if count >= CAP:
            break
        npi = e.get("npi_number")
        if npi in existing_npis or npi in seen_npi:
            continue
        if e["name"].strip().lower() in existing_names:
            continue
        key = (addr_key(e["address"]), e.get("type"))
        if key in seen_addr_type:
            continue
        seen_addr_type.add(key)
        seen_npi.add(npi)
        kept.append(e)
        count += 1
    print(f"{tax:45} raw={len(items):6}  kept(unique,capped)={count:5}")

print(f"\nTotal raw candidates: {raw_total}")
print(f"Total kept for geocoding: {len(kept)}")

with open(os.path.join(SCRATCH, "candidates_raw_full.jsonl"), "w", encoding="utf-8") as f:
    for tax, items in by_tax.items():
        for e in items:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
    for e in kept:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
