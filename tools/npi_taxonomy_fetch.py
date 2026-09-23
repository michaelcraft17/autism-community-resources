"""
NPI Registry taxonomy harvester — step 1 of 4.

Pulls providers/facilities from the free NPI Registry API (no key needed) for a set of
autism/developmental-disability-specific taxonomy codes, across all 50 states + DC.

Pipeline (run in this order from the repo root):
  1. python3 tools/npi_taxonomy_fetch.py      -> tools/npi_scratch/candidates.jsonl
  2. python3 tools/npi_taxonomy_prefilter.py  -> caps + dedupes candidates.jsonl in place
                                                  (keeps at most PER_TAXONOMY_CAP unique
                                                  addresses per taxonomy, before the slow
                                                  geocoding step, so you don't waste calls
                                                  geocoding things that would be dropped
                                                  as duplicates anyway)
  3. python3 tools/npi_taxonomy_geocode.py    -> tools/npi_scratch/geocoded.jsonl + failed.jsonl
                                                  (resumable — safe to Ctrl+C and rerun)
  4. python3 tools/npi_taxonomy_merge.py      -> appends into community_resources.json
  5. node gen_community_data.js  is WRONG — use tools/regen_community_data_js.py's format
     instead (see that script). Then commit + push, and let GitHub Pages rebuild.

To add MORE taxonomies later: find the code on the official NUCC list
(https://www.nucc.org/index.php/code-sets-mainmenu-41/provider-taxonomy-mainmenu-40/csv-mainmenu-57),
then test your search string works standalone before adding it here — the NPI API's
taxonomy_description search only matches specific indexed phrases (usually the CSV's
"Classification" or "Specialization" column text, not the "Display Name" column), e.g.:

  curl -s "https://npiregistry.cms.hhs.gov/api/?version=2.1&taxonomy_description=<your query>&limit=3"

If you get {"Errors": [...]} back, the string doesn't match — try the literal
Classification or Specialization text from the CSV instead. Once you get a result back,
confirm the code you want is actually in its taxonomies[].code list (the API's text
match can be broader than the exact code), then add an entry to TAXONOMY_QUERIES below.
"""
import json, re, time, os

import requests

NPI_BASE = "https://npiregistry.cms.hhs.gov/api/"
STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY",
          "LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND",
          "OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"]

ACRONYMS = {"ABA","LLC","LLP","INC","PLLC","PC","LTD","DBA","PA","PLC","OT","PT","SLP","BCBA","BCABA","RBT","USA","PSC","PS","IDD"}

def smart_title(raw):
    out = []
    for w in raw.split():
        core = re.sub(r'[^A-Za-z0-9]', '', w).upper()
        out.append(re.sub(r'[A-Za-z]+', core, w) if core in ACRONYMS and core else (w.capitalize() if w.isalpha() else w.title()))
    return ' '.join(out)

# taxonomy code -> {search query (must work standalone against the API — see docstring),
# enumeration_type (NPI-1 = individual, NPI-2 = organization), directory `type`,
# `services` tags, and a description template using {name}}.
# Already used (don't re-add): 103K00000X Behavior Analyst, 2080P0006X Developmental-
# Behavioral Pediatrics, 2080P0008X/2084P0005X Neurodevelopmental Disabilities,
# 2084P0804X Child & Adolescent Psychiatry, 2084N0402X Child Neurology.
TAXONOMY_QUERIES = {
    "106E00000X": {"q": "Assistant Behavior Analyst", "enum": "NPI-1", "type": "therapy",
        "services": ["ABA / Behavioral Therapy"], "desc": "{name} is a registered Assistant Behavior Analyst (BCaBA-level, NPI registry)."},
    "106S00000X": {"q": "Behavior Technician", "enum": "NPI-1", "type": "therapy",
        "services": ["ABA / Behavioral Therapy"], "desc": "{name} is a registered Behavior Technician (NPI registry)."},
    "103G00000X": {"q": "Clinical Neuropsychologist", "enum": "NPI-1", "type": "medical",
        "services": ["Neuropsychological Evaluation", "Autism Diagnosis & Evaluation"], "desc": "{name} is a board-certified clinical neuropsychologist (NPI registry)."},
    "103TM1800X": {"q": "Intellectual & Developmental Disabilities", "enum": "NPI-1", "type": "medical",
        "services": ["Intellectual & Developmental Disabilities Psychology"], "desc": "{name} is a psychologist specializing in intellectual & developmental disabilities (NPI registry)."},
    "222Q00000X": {"q": "Developmental Therapist", "enum": "NPI-1", "type": "therapy",
        "services": ["Developmental Therapy"], "desc": "{name} is a registered developmental therapist (NPI registry)."},
    "261QD1600X": {"q": "Developmental Disabilities", "enum": "NPI-2", "type": "medical",
        "services": ["Developmental Disabilities Clinic"], "desc": "{name} is a developmental disabilities clinic/center (NPI registry)."},
    "261QH0700X": {"q": "Hearing and Speech", "enum": "NPI-2", "type": "medical",
        "services": ["Speech & Hearing Services"], "desc": "{name} is a hearing and speech clinic/center (NPI registry)."},
    "251C00000X": {"q": "Day Training, Developmentally Disabled Services", "enum": "NPI-2", "type": "social",
        "services": ["Day Program", "Developmentally Disabled Services"], "desc": "{name} is a day training agency for individuals with developmental disabilities (NPI registry)."},
    "315P00000X": {"q": "Intermediate Care Facility, Intellectual Disabilities", "enum": "NPI-2", "type": "general_support",
        "services": ["Residential Care", "Intellectual Disabilities Services"], "desc": "{name} is an intermediate care facility for individuals with intellectual disabilities (NPI registry)."},
    "320600000X": {"q": "Residential Treatment Facility, Intellectual and/or Developmental Disabilities", "enum": "NPI-2", "type": "general_support",
        "services": ["Residential Treatment", "Intellectual & Developmental Disabilities Services"], "desc": "{name} is a residential treatment facility for individuals with intellectual and/or developmental disabilities (NPI registry)."},
    "320900000X": {"q": "Community Based Residential Treatment Facility, Intellectual and/or Developmental Disabilities", "enum": "NPI-2", "type": "general_support",
        "services": ["Community-Based Residential Treatment", "Intellectual & Developmental Disabilities Services"], "desc": "{name} is a community-based residential treatment facility for individuals with intellectual and/or developmental disabilities (NPI registry)."},
    "385HR2060X": {"q": "Respite Care, Intellectual and/or Developmental Disabilities, Child", "enum": "NPI-2", "type": "general_support",
        "services": ["Respite Care", "In-home Services"], "desc": "{name} provides respite care for children with intellectual and/or developmental disabilities (NPI registry)."},
}

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "npi_scratch")
os.makedirs(SCRATCH, exist_ok=True)
JSONL_PATH = os.path.join(SCRATCH, "candidates.jsonl")
PROGRESS_PATH = os.path.join(SCRATCH, "progress.json")

def location_address(result):
    for a in result.get("addresses", []):
        if a.get("address_purpose") == "LOCATION":
            return a
    addrs = result.get("addresses", [])
    return addrs[0] if addrs else {}

def fetch_state_query(state, q, enum_type):
    out = []
    skip = 0
    while True:
        params = {"version": "2.1", "taxonomy_description": q, "state": state,
                   "enumeration_type": enum_type, "limit": 200, "skip": skip}
        try:
            r = requests.get(NPI_BASE, params=params, timeout=20)
            r.raise_for_status()
            j = r.json()
            if "Errors" in j:
                break
            results = j.get("results", [])
        except Exception as ex:
            print(f"  ERROR {state}/{q} skip={skip}: {ex}", flush=True)
            break
        out.extend(results)
        if len(results) < 200:
            break
        skip += 200
        if skip > 1000:
            break  # known NPI API ceiling for a single state/taxonomy query
        time.sleep(0.15)
    return out

def load_progress():
    if os.path.exists(PROGRESS_PATH):
        return set(json.load(open(PROGRESS_PATH, encoding="utf-8")))
    return set()

def save_progress(done):
    tmp = PROGRESS_PATH + ".tmp"
    json.dump(sorted(done), open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, PROGRESS_PATH)

def load_seen_npi():
    seen = set()
    if os.path.exists(JSONL_PATH):
        for line in open(JSONL_PATH, encoding="utf-8"):
            line = line.strip()
            if not line: continue
            try:
                seen.add(json.loads(line)["npi_number"])
            except Exception:
                continue
    return seen

if __name__ == "__main__":
    existing = json.load(open(os.path.join(REPO, "community_resources.json"), encoding="utf-8"))
    existing_names = {e["name"].strip().lower() for e in existing}
    existing_npis = {e.get("npi_number") for e in existing if e.get("npi_number")}

    done_keys = load_progress()
    seen_npi = load_seen_npi() | existing_npis
    print(f"Resuming: {len(done_keys)} state/tax pairs done, {len(seen_npi)} NPIs already known.", flush=True)

    jf = open(JSONL_PATH, "a", encoding="utf-8")
    t0 = time.time()

    for code, meta in TAXONOMY_QUERIES.items():
        for state in STATES:
            key = f"{state}|{code}"
            if key in done_keys:
                continue
            raw = fetch_state_query(state, meta["q"], meta["enum"])
            added = 0
            for r in raw:
                npi_num = r.get("number")
                if npi_num in seen_npi:
                    continue
                tax_codes = {t.get("code") for t in r.get("taxonomies", [])}
                if code not in tax_codes:
                    continue  # the API's text search is broader than the exact code
                basic = r.get("basic", {})
                if meta["enum"] == "NPI-1":
                    first = basic.get("first_name", "").strip().title()
                    last = basic.get("last_name", "").strip().title()
                    credential = (basic.get("credential") or "").strip().rstrip(".")
                    if not (first and last):
                        continue
                    name = f"{first} {last}" + (f", {credential}" if credential else "")
                else:
                    org = basic.get("organization_name", "").strip()
                    if not org:
                        continue
                    name = smart_title(org)
                if name.lower() in existing_names:
                    continue

                addr = location_address(r)
                street = (addr.get("address_1") or "").strip()
                city = (addr.get("city") or "").strip()
                st = (addr.get("state") or "").strip()
                zip5 = (addr.get("postal_code") or "")[:5]
                if not (street and city and st and zip5):
                    continue
                phone = addr.get("telephone_number", "")

                seen_npi.add(npi_num)
                entry = {
                    "name": name,
                    "address": f"{street}, {city}, {st} {zip5}",
                    "phone": phone,
                    "website": "",
                    "type": meta["type"],
                    "source": "npi-registry",
                    "services": meta["services"],
                    "description": meta["desc"].format(name=name),
                    "npi_number": npi_num,
                }
                jf.write(json.dumps(entry, ensure_ascii=False) + "\n")
                added += 1
            jf.flush(); os.fsync(jf.fileno())
            done_keys.add(key)
            if added:
                print(f"{code} {state}: +{added} (raw={len(raw)})", flush=True)
            save_progress(done_keys)

    jf.close()
    total = len(load_seen_npi())
    print(f"\nDONE in {time.time()-t0:.0f}s. Total candidates in jsonl: {total}", flush=True)
