import json, os, re, time
import requests

SCRATCH = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
FILES = ["ndrn_pa.jsonl", "aucd_ucedd.jsonl"]

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

def clean_address_for_geocoding(addr):
    # strip parenthetical / multi-line junk some entries picked up (e.g. "Office Location:, ... Mailing Address:, ...")
    addr = addr.split("Mailing Address")[0]
    addr = re.sub(r"Office Location:,?\s*", "", addr)
    return addr.strip().strip(",")

def try_census(addr):
    try:
        r = requests.get(CENSUS_URL, params={
            "address": addr, "benchmark": "Public_AR_Current", "format": "json"
        }, timeout=15)
        r.raise_for_status()
        matches = r.json().get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0]["coordinates"]
            return {"lat": coords["y"], "lng": coords["x"]}
    except Exception as ex:
        print(f"    census error: {ex}", flush=True)
    return None

def try_nominatim(addr):
    try:
        r = requests.get(NOMINATIM_URL, params={
            "q": addr, "format": "json", "limit": 1
        }, headers={"User-Agent": "autism-community-resources-geocoder/1.0"}, timeout=15)
        r.raise_for_status()
        results = r.json()
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception as ex:
        print(f"    nominatim error: {ex}", flush=True)
    return None

def process_file(fname):
    path = os.path.join(SCRATCH, fname)
    entries = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    changed = 0
    for e in entries:
        if e.get("coordinates"):
            continue
        addr = clean_address_for_geocoding(e["address"])
        coords = try_census(addr)
        time.sleep(0.3)
        if not coords:
            coords = try_nominatim(addr)
            time.sleep(1.0)  # Nominatim usage policy: max 1 req/sec
        if coords:
            e["coordinates"] = coords
            changed += 1
            print(f"  OK  {e['name']}: {coords}", flush=True)
        else:
            print(f"  FAIL {e['name']}: {addr}", flush=True)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    still_missing = sum(1 for e in entries if not e.get("coordinates"))
    print(f"{fname}: filled {changed}, still missing {still_missing}", flush=True)

if __name__ == "__main__":
    for fname in FILES:
        print(f"=== {fname} ===", flush=True)
        process_file(fname)
