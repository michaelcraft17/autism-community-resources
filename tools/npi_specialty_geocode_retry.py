import json, os, time
import requests

SCRATCH = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
PATH = os.path.join(SCRATCH, "npi_specialty_geocoded.jsonl")
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

def try_census(addr):
    try:
        r = requests.get(CENSUS_URL, params={
            "address": addr, "benchmark": "Public_AR_Current", "format": "json"
        }, timeout=15)
        r.raise_for_status()
        matches = r.json().get("result", {}).get("addressMatches", [])
        if matches:
            c = matches[0]["coordinates"]
            return {"lat": c["y"], "lng": c["x"]}
    except Exception:
        pass
    return None

if __name__ == "__main__":
    entries = [json.loads(l) for l in open(PATH, encoding="utf-8") if l.strip()]
    print(f"Total: {len(entries)}", flush=True)
    filled = 0
    for i, e in enumerate(entries):
        if e.get("coordinates"):
            continue
        coords = try_census(e["address"])
        if coords:
            e["coordinates"] = coords
            filled += 1
        if i % 200 == 0:
            print(f"  progress {i}/{len(entries)}, filled so far {filled}", flush=True)
        time.sleep(0.2)

    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PATH)
    still_null = sum(1 for e in entries if not e.get("coordinates"))
    print(f"DONE. filled {filled} more, still null: {still_null}", flush=True)
