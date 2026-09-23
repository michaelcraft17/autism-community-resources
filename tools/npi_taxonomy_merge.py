"""
Step 4 of 4 — merge npi_scratch/geocoded.jsonl into community_resources.json.

Dedupes by npi_number, by name, and by (address, type) so multiple staff enumerated at
one clinic don't produce duplicate map pins, and caps each taxonomy's contribution at
PER_TAXONOMY_CAP entries (should already be true post-prefilter, this is a safety net).

After this: regenerate community_data.js using tools/regen_community_data_js.py's
approach (`window.communityData = [...]`), NOT the root gen_community_data.js, which
writes `const communityResourcesData = ...` — a variable index.html never reads, so the
site silently falls back to its tiny hardcoded sample dataset if you use it by mistake.
Then commit + push and let GitHub Pages rebuild (check with:
  gh api repos/michaelcraft17/autism-community-resources/pages/builds/latest
).
"""
import json, os, re
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "npi_scratch")
JSON_FILE = os.path.join(REPO, "community_resources.json")
GEOCODED_PATH = os.path.join(SCRATCH, "geocoded.jsonl")

PER_TAXONOMY_CAP = 3000  # keep in sync with CAP in npi_taxonomy_prefilter.py

DEFAULT_SUGGESTED = {
    "free_services": False, "telehealth": False, "in_home": False,
    "accepts_medicaid": False, "early_intervention": False,
    "bilingual": False, "wheelchair_accessible": False,
}

def addr_key(addr):
    street = addr.split(",")[0]
    street = re.sub(r'\s*(STE|SUITE|UNIT|#)\s*\S+$', '', street.upper()).strip()
    rest = ",".join(addr.split(",")[1:])
    return re.sub(r'\s+', ' ', (street + "|" + rest).upper()).strip()

existing = json.load(open(JSON_FILE, encoding="utf-8"))
existing_names = {e["name"].strip().lower() for e in existing}
existing_npis = {e.get("npi_number") for e in existing if e.get("npi_number")}
existing_addr_type = {(addr_key(e["address"]), e.get("type")) for e in existing if e.get("address")}

candidates = []
with open(GEOCODED_PATH, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            candidates.append(json.loads(line))

seen_npi = set()
seen_addr_type = set(existing_addr_type)
kept_by_taxonomy = defaultdict(list)
skipped_name = skipped_npi = skipped_addr = skipped_cap = 0

for e in candidates:
    npi = e.get("npi_number")
    name_key = e["name"].strip().lower()
    if npi in existing_npis or npi in seen_npi:
        skipped_npi += 1; continue
    if name_key in existing_names:
        skipped_name += 1; continue
    key = (addr_key(e["address"]), e.get("type"))
    if key in seen_addr_type:
        skipped_addr += 1; continue
    taxonomy = e.get("services", ["?"])[0]
    if len(kept_by_taxonomy[taxonomy]) >= PER_TAXONOMY_CAP:
        skipped_cap += 1; continue
    e["suggested"] = dict(DEFAULT_SUGGESTED)
    blob = (" ".join(e.get("services", [])) + " " + e["description"]).lower()
    if "in-home" in blob or "respite" in blob:
        e["suggested"]["in_home"] = True
    kept_by_taxonomy[taxonomy].append(e)
    seen_npi.add(npi)
    seen_addr_type.add(key)
    existing_names.add(name_key)

new_entries = [e for lst in kept_by_taxonomy.values() for e in lst]

print(f"Candidates: {len(candidates)}")
print(f"New entries to add: {len(new_entries)}  "
      f"(skipped: {skipped_npi} dup-npi, {skipped_name} dup-name, {skipped_addr} dup-address+type, {skipped_cap} over per-category cap)")

updated = existing + new_entries
with open(JSON_FILE, "w", encoding="utf-8") as f:
    json.dump(updated, f, indent=2, ensure_ascii=False)

print(f"community_resources.json now has {len(updated)} entries (+{len(new_entries)}).")

for k, v in sorted(kept_by_taxonomy.items(), key=lambda kv: -len(kv[1])):
    print(f"  {len(v):6}  {k}")
