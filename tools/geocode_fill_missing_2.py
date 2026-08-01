import json, os, re, time
import requests

SCRATCH = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
FILES = ["ndrn_pa.jsonl", "aucd_ucedd.jsonl"]
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

def city_level_query(addr):
    # take the last 2-3 comma-separated parts (city, state zip) - drop street/box/suite noise
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if len(parts) >= 2:
        return ", ".join(parts[-2:])
    return addr

def try_nominatim(q):
    try:
        r = requests.get(NOMINATIM_URL, params={
            "q": q, "format": "json", "limit": 1
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
        q = city_level_query(e["address"])
        coords = try_nominatim(q)
        time.sleep(1.0)
        if coords:
            e["coordinates"] = coords
            e["_coords_approx_city_level"] = True
            changed += 1
            print(f"  OK (city-level) {e['name']}: {coords}", flush=True)
        else:
            print(f"  STILL FAIL {e['name']}: {q}", flush=True)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    still_missing = sum(1 for e in entries if not e.get("coordinates"))
    print(f"{fname}: filled {changed} more, still missing {still_missing}", flush=True)

if __name__ == "__main__":
    for fname in FILES:
        print(f"=== {fname} ===", flush=True)
        process_file(fname)
