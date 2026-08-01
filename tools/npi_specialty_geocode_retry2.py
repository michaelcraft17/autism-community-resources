import json, os, time
import requests

SCRATCH = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
PATH = os.path.join(SCRATCH, "npi_specialty_geocoded.jsonl")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

def try_nominatim(addr):
    try:
        r = requests.get(NOMINATIM_URL, params={
            "q": addr, "format": "json", "limit": 1
        }, headers={"User-Agent": "autism-community-resources-geocoder/1.0"}, timeout=15)
        r.raise_for_status()
        results = r.json()
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception:
        pass
    return None

def save(entries):
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PATH)

if __name__ == "__main__":
    entries = [json.loads(l) for l in open(PATH, encoding="utf-8") if l.strip()]
    null_idx = [i for i, e in enumerate(entries) if not e.get("coordinates")]
    print(f"Total: {len(entries)}, nulls to retry: {len(null_idx)}", flush=True)
    filled = 0
    for n, idx in enumerate(null_idx):
        e = entries[idx]
        coords = try_nominatim(e["address"])
        if not coords:
            parts = [p.strip() for p in e["address"].split(",") if p.strip()]
            if len(parts) >= 2:
                coords = try_nominatim(", ".join(parts[-2:]))
        if coords:
            e["coordinates"] = coords
            filled += 1
        if n % 50 == 0:
            save(entries)
            print(f"  progress {n}/{len(null_idx)}, filled so far {filled} (checkpoint saved)", flush=True)
        time.sleep(1.05)

    save(entries)
    still_null = sum(1 for e in entries if not e.get("coordinates"))
    print(f"DONE. filled {filled} more, still null: {still_null}", flush=True)
