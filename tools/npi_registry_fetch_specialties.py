import json, re, time, os
import requests

NPI_BASE = "https://npiregistry.cms.hhs.gov/api/"
STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY",
          "LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND",
          "OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"]

# search string -> (accepted taxonomy codes, services list, description template)
TAXONOMY_QUERIES = {
    "Developmental - Behavioral Pediatrics": {
        "codes": {"2080P0006X"},
        "services": ["Developmental-Behavioral Pediatrics", "Autism Diagnosis & Evaluation"],
        "desc": "{name} is a board-certified developmental-behavioral pediatrician (NPI registry).",
    },
    "Neurodevelopmental Disabilities": {
        "codes": {"2080P0008X", "2084P0005X"},
        "services": ["Neurodevelopmental Disabilities", "Autism Diagnosis & Evaluation"],
        "desc": "{name} specializes in neurodevelopmental disabilities (NPI registry).",
    },
    "Child & Adolescent Psychiatry": {
        "codes": {"2084P0804X"},
        "services": ["Child & Adolescent Psychiatry", "Medication Management"],
        "desc": "{name} is a board-certified child & adolescent psychiatrist (NPI registry).",
    },
    "Neurology with Special Qualifications in Child Neurology": {
        "codes": {"2084N0402X"},
        "services": ["Pediatric Neurology", "Child Neurology"],
        "desc": "{name} is a board-certified pediatric (child) neurologist (NPI registry).",
    },
}

SCRATCH = r"C:\Users\Lenovo\AppData\Local\Temp\claude\C--Users-Lenovo\01dd4fda-bed2-4ee1-8d82-7a492c36c3ab\scratchpad"
JSONL_PATH = os.path.join(SCRATCH, "npi_specialty_candidates.jsonl")
PROGRESS_PATH = os.path.join(SCRATCH, "npi_specialty_progress.json")

def title_name(raw):
    if not raw:
        return ""
    return " ".join(w.capitalize() for w in raw.strip().split())

def location_address(result):
    for a in result.get("addresses", []):
        if a.get("address_purpose") == "LOCATION":
            return a
    addrs = result.get("addresses", [])
    return addrs[0] if addrs else {}

def fetch_state_query(state, query):
    out = []
    skip = 0
    while True:
        params = {
            "version": "2.1", "taxonomy_description": query, "state": state,
            "enumeration_type": "NPI-1", "limit": 200, "skip": skip,
        }
        try:
            r = requests.get(NPI_BASE, params=params, timeout=20)
            r.raise_for_status()
            j = r.json()
            if "Errors" in j:
                print(f"  API ERROR {state}/{query}: {j['Errors']}", flush=True)
                break
            results = j.get("results", [])
        except Exception as ex:
            print(f"  ERROR {state}/{query} skip={skip}: {ex}", flush=True)
            break
        out.extend(results)
        if len(results) < 200:
            break
        skip += 200
        if skip > 1000:
            print(f"  WARNING {state}/{query}: hit skip>1000, results may be truncated (NPI API ceiling)", flush=True)
            break
        time.sleep(0.2)
    return out

def load_progress():
    if os.path.exists(PROGRESS_PATH):
        return set(json.load(open(PROGRESS_PATH, encoding="utf-8")))
    return set()

def save_progress(done):
    tmp = PROGRESS_PATH + ".tmp"
    json.dump(sorted(done), open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, PROGRESS_PATH)

def load_existing_jsonl_npis():
    seen = set()
    if os.path.exists(JSONL_PATH):
        with open(JSONL_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                seen.add(e["npi_number"])
    return seen

if __name__ == "__main__":
    done_keys = load_progress()
    seen_npi = load_existing_jsonl_npis()
    print(f"Resuming: {len(done_keys)} state/query pairs already done, {len(seen_npi)} candidates already saved.", flush=True)

    jf = open(JSONL_PATH, "a", encoding="utf-8")

    for state in STATES:
        for query, meta in TAXONOMY_QUERIES.items():
            key = f"{state}|{query}"
            if key in done_keys:
                continue
            raw = fetch_state_query(state, query)
            added = 0
            for r in raw:
                npi_num = r.get("number")
                if npi_num in seen_npi:
                    continue

                # verify against exact accepted taxonomy codes (API description match is fuzzy/over-inclusive)
                tax_codes = {t.get("code") for t in r.get("taxonomies", [])}
                if not (tax_codes & meta["codes"]):
                    continue

                basic = r.get("basic", {})
                first = title_name(basic.get("first_name", ""))
                last = title_name(basic.get("last_name", ""))
                credential = (basic.get("credential") or "").strip().rstrip(".")
                if not (first and last):
                    continue
                name = f"{first} {last}" + (f", {credential}" if credential else "")

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
                    "type": "medical",
                    "source": "npi-registry",
                    "services": meta["services"],
                    "description": meta["desc"].format(name=name),
                    "npi_number": npi_num,
                }
                jf.write(json.dumps(entry, ensure_ascii=False) + "\n")
                jf.flush()
                os.fsync(jf.fileno())
                added += 1

            done_keys.add(key)
            save_progress(done_keys)
            print(f"{state} / {query}: {len(raw)} raw, +{added} new candidates, running total={len(seen_npi)}", flush=True)

    jf.close()
    print(f"\nDONE. Total candidate entries (pre-geocoding): {len(seen_npi)}", flush=True)
