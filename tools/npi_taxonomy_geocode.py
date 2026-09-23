"""
Step 3 of 4 — geocode npi_scratch/candidates.jsonl (after prefiltering) into
npi_scratch/geocoded.jsonl (+ failed.jsonl for addresses nothing could resolve).

Resumable: safe to Ctrl+C or kill and rerun — it skips any npi_number already written
to geocoded.jsonl or failed.jsonl. If it hangs on a Census batch call, just kill it
(`kill <pid>`) and rerun; nothing already written is lost. The Census bulk geocoder
occasionally times out or 502s on a whole chunk with no partial output — if that
happens, just rerun this script again afterward (once) to sweep up whatever chunk(s)
got dropped, same resumability applies.

Tries, in order: Census Bureau's free bulk batch geocoder (up to CHUNK_SIZE addresses
per request) -> Census's single-address endpoint for anything the batch call missed ->
Nominatim (OpenStreetMap) as a last resort, rate-limited to 1 req/sec per their usage
policy (only sleeps when Nominatim is actually called, not on every fallback attempt).
"""
import json, csv, io, os, time

import requests

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "npi_scratch")
CANDIDATES_PATH = os.path.join(SCRATCH, "candidates.jsonl")
GEOCODED_PATH = os.path.join(SCRATCH, "geocoded.jsonl")
FAILED_PATH = os.path.join(SCRATCH, "failed.jsonl")
CHUNK_SIZE = 2000  # keep modest -- larger batches risk the Census endpoint's own timeout

CENSUS_BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CENSUS_ONE = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

def load_candidates():
    entries = []
    seen = set()
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            e = json.loads(line)
            if e["npi_number"] in seen: continue
            seen.add(e["npi_number"])
            entries.append(e)
    return entries

def already_done():
    done = set()
    for path in (GEOCODED_PATH, FAILED_PATH):
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if not line: continue
                try:
                    done.add(json.loads(line)["npi_number"])
                except Exception:
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

def geocode_chunk_census(chunk):
    buf = io.StringIO()
    w = csv.writer(buf)
    id_to_entry = {}
    for i, e in enumerate(chunk):
        street, city, state, zip5 = parse_address(e["address"])
        w.writerow([i, street, city, state, zip5])
        id_to_entry[str(i)] = e
    resp = requests.post(CENSUS_BATCH,
        files={"addressFile": ("batch.csv", buf.getvalue().encode("utf-8"), "text/csv")},
        data={"benchmark": "Public_AR_Current"}, timeout=600)
    resp.raise_for_status()
    results = {}
    reader = csv.reader(io.StringIO(resp.text))
    for row in reader:
        if len(row) < 6: continue
        rid, match = row[0], row[2]
        if match == "Match":
            try:
                lng, lat = row[5].split(",")
                results[rid] = {"lat": float(lat), "lng": float(lng)}
            except Exception:
                pass
    return id_to_entry, results

def try_census_one(addr):
    try:
        r = requests.get(CENSUS_ONE, params={"address": addr, "benchmark": "Public_AR_Current", "format": "json"}, timeout=15)
        r.raise_for_status()
        matches = r.json().get("result", {}).get("addressMatches", [])
        if matches:
            c = matches[0]["coordinates"]
            return {"lat": c["y"], "lng": c["x"]}
    except Exception:
        pass
    return None

def try_nominatim(addr):
    try:
        r = requests.get(NOMINATIM, params={"q": addr, "format": "json", "limit": 1},
                          headers={"User-Agent": "autism-community-resources-geocoder/1.0"}, timeout=15)
        r.raise_for_status()
        res = r.json()
        if res:
            return {"lat": float(res[0]["lat"]), "lng": float(res[0]["lon"])}
    except Exception:
        pass
    return None

if __name__ == "__main__":
    entries = load_candidates()
    done = already_done()
    todo = [e for e in entries if e["npi_number"] not in done]
    print(f"Total candidates: {len(entries)}, already geocoded/failed: {len(done)}, remaining: {len(todo)}", flush=True)

    gf = open(GEOCODED_PATH, "a", encoding="utf-8")
    ff = open(FAILED_PATH, "a", encoding="utf-8")

    for i in range(0, len(todo), CHUNK_SIZE):
        chunk = todo[i:i+CHUNK_SIZE]
        print(f"Census batch {i}-{i+len(chunk)} of {len(todo)}...", flush=True)
        try:
            id_to_entry, results = geocode_chunk_census(chunk)
        except Exception as ex:
            # Whole chunk lost on a transient timeout/502 -- rerun the script afterward
            # to pick these back up (they're still "todo" next run, nothing is corrupted).
            print(f"  batch failed: {ex}", flush=True)
            id_to_entry, results = {}, {}

        unmatched = []
        matched_count = 0
        for rid, e in id_to_entry.items():
            coords = results.get(rid)
            if coords:
                e["coordinates"] = coords
                gf.write(json.dumps(e, ensure_ascii=False) + "\n")
                matched_count += 1
            else:
                unmatched.append(e)
        gf.flush(); os.fsync(gf.fileno())
        print(f"  census matched {matched_count}/{len(chunk)}, retrying {len(unmatched)} individually...", flush=True)

        for e in unmatched:
            coords = try_census_one(e["address"])
            if not coords:
                coords = try_nominatim(e["address"])
                time.sleep(1.0)  # nominatim politeness -- only when nominatim was actually called
            if coords:
                e["coordinates"] = coords
                gf.write(json.dumps(e, ensure_ascii=False) + "\n")
            else:
                ff.write(json.dumps(e, ensure_ascii=False) + "\n")
        gf.flush(); os.fsync(gf.fileno()); ff.flush(); os.fsync(ff.fileno())

    gf.close(); ff.close()
    print("DONE geocoding.", flush=True)
