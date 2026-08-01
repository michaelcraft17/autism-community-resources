import json, csv, io, os
import requests

SCRATCH = r"C:\Users\Lenovo\AppData\Local\Temp\claude\C--Users-Lenovo\01dd4fda-bed2-4ee1-8d82-7a492c36c3ab\scratchpad"
CANDIDATES_PATH = f"{SCRATCH}\\npi_specialty_candidates.jsonl"
GEOCODED_PATH = f"{SCRATCH}\\npi_specialty_geocoded.jsonl"
CHUNK_SIZE = 2000

def load_candidates():
    entries = []
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries

def already_geocoded_npis():
    done = set()
    if os.path.exists(GEOCODED_PATH):
        with open(GEOCODED_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    done.add(e["npi_number"])
                except json.JSONDecodeError:
                    continue
    return done

def parse_address(addr):
    parts = addr.split(",")
    street = parts[0].strip()
    city = parts[1].strip() if len(parts) > 1 else ""
    state_zip = parts[2].strip().split() if len(parts) > 2 else ["", ""]
    state = state_zip[0] if state_zip else ""
    zip5 = state_zip[1] if len(state_zip) > 1 else ""
    return street, city, state, zip5

def geocode_chunk(chunk):
    buf = io.StringIO()
    w = csv.writer(buf)
    id_to_entry = {}
    for i, e in enumerate(chunk):
        street, city, state, zip5 = parse_address(e["address"])
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
        results[entry["npi_number"]] = coords
    return results

if __name__ == "__main__":
    all_entries = load_candidates()
    done_npis = already_geocoded_npis()
    todo = [e for e in all_entries if e["npi_number"] not in done_npis]
    print(f"Total: {len(all_entries)}, already geocoded: {len(done_npis)}, remaining: {len(todo)}", flush=True)

    out = open(GEOCODED_PATH, "a", encoding="utf-8")
    for start in range(0, len(todo), CHUNK_SIZE):
        chunk = todo[start:start + CHUNK_SIZE]
        print(f"Geocoding chunk {start}-{start+len(chunk)}...", flush=True)
        coords_by_npi = geocode_chunk(chunk)
        matched = 0
        for e in chunk:
            coords = coords_by_npi.get(e["npi_number"])
            if coords:
                matched += 1
            e2 = dict(e)
            e2["coordinates"] = coords
            out.write(json.dumps(e2, ensure_ascii=False) + "\n")
        out.flush()
        os.fsync(out.fileno())
        print(f"  chunk done: {matched}/{len(chunk)} matched", flush=True)
    out.close()
    print("DONE geocoding.", flush=True)
