import json, re, time, os
import requests

NPI_BASE = "https://npiregistry.cms.hhs.gov/api/"
TAXONOMY_DESC = "Behavior Analyst"
STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY",
          "LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND",
          "OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"]

ACRONYMS = {"ABA","LLC","LLP","INC","PLLC","PC","LTD","DBA","PA","PLC","OT","PT","SLP","BCBA","USA","PSC","PS"}

SCRATCH = r"C:\Users\Lenovo\AppData\Local\Temp\claude\C--Users-Lenovo\7e21213a-f5c2-4aaf-9aef-bdcdf5c327ab\scratchpad"
JSONL_PATH = os.path.join(SCRATCH, "npi_candidates.jsonl")
PROGRESS_PATH = os.path.join(SCRATCH, "npi_progress.json")

def smart_title(raw):
    out = []
    for w in raw.split():
        core = re.sub(r'[^A-Za-z0-9]', '', w).upper()
        if core in ACRONYMS and core:
            out.append(re.sub(r'[A-Za-z]+', core, w))
        else:
            out.append(w.capitalize() if w.isalpha() else w.title())
    return ' '.join(out)

def location_address(result):
    for a in result.get("addresses", []):
        if a.get("address_purpose") == "LOCATION":
            return a
    addrs = result.get("addresses", [])
    return addrs[0] if addrs else {}

def fetch_state(state):
    out = []
    skip = 0
    while True:
        params = {
            "version": "2.1", "taxonomy_description": TAXONOMY_DESC, "state": state,
            "enumeration_type": "NPI-2", "limit": 200, "skip": skip,
        }
        try:
            r = requests.get(NPI_BASE, params=params, timeout=20)
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception as ex:
            print(f"  ERROR {state} skip={skip}: {ex}", flush=True)
            break
        out.extend(results)
        if len(results) < 200:
            break
        skip += 200
        if skip > 1000:
            print(f"  WARNING {state}: hit skip>1000, results may be truncated (NPI API ceiling)", flush=True)
            break
        time.sleep(0.2)
    return out

def load_progress():
    if os.path.exists(PROGRESS_PATH):
        return set(json.load(open(PROGRESS_PATH, encoding="utf-8")))
    return set()

def save_progress(done_states):
    tmp = PROGRESS_PATH + ".tmp"
    json.dump(sorted(done_states), open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, PROGRESS_PATH)

def load_existing_jsonl_keys():
    seen_npi, seen_addr_phone, count = set(), set(), 0
    if os.path.exists(JSONL_PATH):
        with open(JSONL_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue  # last line may be a partial write from a crash - just skip it
                seen_npi.add(e["npi_number"])
                key = (re.sub(r'\W+','', e["address"].split(",")[0]).upper(), re.sub(r'\D','', e["phone"]))
                seen_addr_phone.add(key)
                count += 1
    return seen_npi, seen_addr_phone, count

if __name__ == "__main__":
    existing = json.load(open(r"C:\Users\Lenovo\autism-community-resources\community_resources.json", encoding="utf-8"))
    existing_names = {e["name"].strip().lower() for e in existing}

    done_states = load_progress()
    seen_npi, seen_addr_phone, total_so_far = load_existing_jsonl_keys()
    print(f"Resuming: {len(done_states)} states already done, {total_so_far} candidates already saved.", flush=True)

    jf = open(JSONL_PATH, "a", encoding="utf-8")

    for state in STATES:
        if state in done_states:
            continue
        raw = fetch_state(state)
        added_this_state = 0
        for r in raw:
            npi_num = r.get("number")
            if npi_num in seen_npi:
                continue

            basic = r.get("basic", {})
            org_name = basic.get("organization_name", "").strip()
            if not org_name:
                continue
            name = smart_title(org_name)
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

            dedup_key = (re.sub(r'\W+','',street).upper(), re.sub(r'\D','',phone))
            if dedup_key in seen_addr_phone:
                continue
            seen_addr_phone.add(dedup_key)
            seen_npi.add(npi_num)

            entry = {
                "name": name,
                "address": f"{street}, {city}, {st} {zip5}",
                "phone": phone,
                "website": "",
                "type": "therapy",
                "source": "npi-registry",
                "services": ["ABA / Behavioral Therapy"],
                "description": f"{name} is a registered Applied Behavior Analysis (ABA) provider (NPI registry).",
                "npi_number": npi_num,
            }
            jf.write(json.dumps(entry, ensure_ascii=False) + "\n")
            jf.flush()
            os.fsync(jf.fileno())
            added_this_state += 1
            total_so_far += 1

        done_states.add(state)
        save_progress(done_states)
        print(f"{state}: {len(raw)} raw, +{added_this_state} new candidates, running total={total_so_far}", flush=True)

    jf.close()
    print(f"\nDONE. Total candidate entries (pre-geocoding): {total_so_far}", flush=True)
