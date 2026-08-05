import json, csv, io, os, time
import requests

SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
SRC = f"{SP}/propublica_autism.jsonl"
CHECKPOINT = f"{SP}/propublica_geocode_checkpoint.jsonl"

def load_entries():
    entries = []
    for i, line in enumerate(open(SRC, encoding="utf-8")):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        d["_uid"] = f"propublica:{i}"
        entries.append(d)
    return entries

def load_checkpoint():
    done = {}
    if os.path.exists(CHECKPOINT):
        for line in open(CHECKPOINT, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            done[d["_uid"]] = d["coordinates"]
    return done

def append_checkpoint(uid, coords):
    with open(CHECKPOINT, "a", encoding="utf-8") as f:
        f.write(json.dumps({"_uid": uid, "coordinates": coords}, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

def parse_street_address(addr):
    parts = addr.split(",")
    street = parts[0].strip()
    city = parts[1].strip() if len(parts) > 1 else ""
    state_zip = parts[2].strip().split() if len(parts) > 2 else ["", ""]
    state = state_zip[0] if state_zip else ""
    zip5 = state_zip[1] if len(state_zip) > 1 else ""
    return street, city, state, zip5

def census_batch(chunk):
    buf = io.StringIO()
    w = csv.writer(buf)
    id_to_entry = {}
    for i, e in enumerate(chunk):
        street, city, state, zip5 = parse_street_address(e["address"])
        w.writerow([i, street, city, state, zip5])
        id_to_entry[str(i)] = e
    resp = requests.post(
        "https://geocoding.geo.census.gov/geocoder/locations/addressbatch",
        files={"addressFile": ("batch.csv", buf.getvalue().encode("utf-8"), "text/csv")},
        data={"benchmark": "Public_AR_Current"},
        timeout=600,
    )
    resp.raise_for_status()
    results = {}
    reader = csv.reader(io.StringIO(resp.text))
    for row in reader:
        if len(row) < 3:
            continue
        rec_id, match_status = row[0], row[2]
        entry = id_to_entry.get(rec_id)
        if entry is None:
            continue
        coords = None
        if match_status == "Match" and len(row) >= 6:
            lon, lat = row[5].split(",")
            coords = {"lat": float(lat), "lng": float(lon)}
        results[entry["_uid"]] = coords
    return results

def census_single(addr):
    try:
        resp = requests.get(
            "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
            params={"address": addr, "benchmark": "Public_AR_Current", "format": "json"},
            timeout=30,
        )
        resp.raise_for_status()
        matches = resp.json().get("result", {}).get("addressMatches", [])
        if matches:
            c = matches[0]["coordinates"]
            return {"lat": float(c["y"]), "lng": float(c["x"])}
    except Exception:
        pass
    return None

def nominatim(query):
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": "autism-community-resources-geocoder/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception:
        pass
    return None

if __name__ == "__main__":
    all_entries = load_entries()
    done = load_checkpoint()
    todo = [e for e in all_entries if e["_uid"] not in done]
    print(f"Total: {len(all_entries)}, already done: {len(done)}, todo: {len(todo)}", flush=True)

    for start in range(0, len(todo), 2000):
        chunk = todo[start:start + 2000]
        coords_by_uid = census_batch(chunk)
        matched = 0
        for e in chunk:
            c = coords_by_uid.get(e["_uid"])
            if c:
                matched += 1
            append_checkpoint(e["_uid"], c)
        print(f"batch {start}-{start+len(chunk)}: {matched}/{len(chunk)} matched", flush=True)

    done = load_checkpoint()
    misses = [e for e in todo if done.get(e["_uid"]) is None]
    print(f"Census batch misses: {len(misses)}", flush=True)

    still_missing = []
    for i, e in enumerate(misses):
        c = census_single(e["address"])
        if c:
            append_checkpoint(e["_uid"], c)
        else:
            still_missing.append(e)
        if (i + 1) % 50 == 0:
            print(f"  census single retry: {i+1}/{len(misses)}", flush=True)

    print(f"Still missing after census single: {len(still_missing)}, trying Nominatim...", flush=True)
    for i, e in enumerate(still_missing):
        c = nominatim(e["address"] + ", USA")
        append_checkpoint(e["_uid"], c)
        time.sleep(1.05)
        if (i + 1) % 25 == 0:
            print(f"  nominatim: {i+1}/{len(still_missing)}", flush=True)

    print("DONE geocoding.", flush=True)
