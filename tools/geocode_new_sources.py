import json, csv, io, os, re, time
import requests

SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"

SOURCES = {
    "asan-affiliate": f"{SP}/asan_affiliates.jsonl",
    "cpir-pti": f"{SP}/cpir_pti.jsonl",
    "ecta-partc": f"{SP}/ecta_partc.jsonl",
    "special-olympics": f"{SP}/special_olympics.jsonl",
    "best-buddies": f"{SP}/best_buddies.jsonl",
}
CHECKPOINT = f"{SP}/new_sources_geocode_checkpoint.jsonl"

def load_all():
    entries = []
    for source, path in SOURCES.items():
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                d["_uid"] = f"{source}:{i}"
                entries.append(d)
    return entries

def load_checkpoint():
    done = {}
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    done[e["_uid"]] = e["coordinates"]
                except json.JSONDecodeError:
                    continue
    return done

def append_checkpoint(uid, coords):
    with open(CHECKPOINT, "a", encoding="utf-8") as f:
        f.write(json.dumps({"_uid": uid, "coordinates": coords}, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

NATIONWIDE_RE = re.compile(r"nationwide|virtual|remote", re.I)
STREETY_RE = re.compile(r"^\d")  # starts with a number => looks like a street address
CITY_STATE_RE = re.compile(r"^[A-Za-z .'-]+,\s*[A-Z]{2}$")

def classify(addr):
    addr = addr.strip()
    if not addr or NATIONWIDE_RE.search(addr):
        return "skip"
    parts = [p.strip() for p in addr.split(",")]
    if len(parts) >= 3 and STREETY_RE.match(parts[0]):
        return "street"
    if CITY_STATE_RE.match(addr):
        return "city"
    if len(parts) == 2 and len(parts[1].split()) <= 1:
        return "city"
    return "street"  # best effort, let census try / fail gracefully

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
    all_entries = load_all()
    already_has_coords = {e["_uid"] for e in all_entries if e.get("coordinates")}
    needs_geocode = [e for e in all_entries if e["_uid"] not in already_has_coords]
    done = load_checkpoint()
    print(f"Total entries: {len(all_entries)}, already had coordinates from source: {len(already_has_coords)}, "
          f"already checkpointed: {len(done)}", flush=True)

    todo = [e for e in needs_geocode if e["_uid"] not in done]

    skip_list, city_list, street_list = [], [], []
    for e in todo:
        cls = classify(e["address"])
        if cls == "skip":
            skip_list.append(e)
        elif cls == "city":
            city_list.append(e)
        else:
            street_list.append(e)

    print(f"skip(nationwide/virtual): {len(skip_list)}, city-level: {len(city_list)}, street: {len(street_list)}", flush=True)

    for e in skip_list:
        append_checkpoint(e["_uid"], None)

    # Census batch pass for street addresses
    if street_list:
        print("Census batch geocoding street addresses...", flush=True)
        for start in range(0, len(street_list), 2000):
            chunk = street_list[start:start + 2000]
            coords_by_uid = census_batch(chunk)
            matched = 0
            for e in chunk:
                coords = coords_by_uid.get(e["_uid"])
                if coords:
                    matched += 1
                append_checkpoint(e["_uid"], coords)
            print(f"  batch chunk {start}-{start+len(chunk)}: {matched}/{len(chunk)} matched", flush=True)

    # reload checkpoint to find remaining nulls among street_list
    done = load_checkpoint()
    remaining_street = [e for e in street_list if done.get(e["_uid"]) is None]
    print(f"Census batch misses needing retry: {len(remaining_street)}", flush=True)

    # Census single-address retry
    still_missing = []
    for i, e in enumerate(remaining_street):
        c = census_single(e["address"])
        if c:
            # overwrite checkpoint entry by appending a newer record (last one wins on load)
            append_checkpoint(e["_uid"], c)
        else:
            still_missing.append(e)
        if (i + 1) % 50 == 0:
            print(f"  census single retry: {i+1}/{len(remaining_street)}", flush=True)

    print(f"Still missing after census single retry: {len(still_missing)}", flush=True)

    # Nominatim fallback for remaining street misses + all city-level entries
    nominatim_queue = still_missing + city_list
    print(f"Nominatim fallback queue: {len(nominatim_queue)}", flush=True)
    for i, e in enumerate(nominatim_queue):
        c = nominatim(e["address"] + ", USA")
        append_checkpoint(e["_uid"], c)
        time.sleep(1.05)
        if (i + 1) % 25 == 0:
            print(f"  nominatim: {i+1}/{len(nominatim_queue)}", flush=True)

    print("DONE geocoding pass.", flush=True)
