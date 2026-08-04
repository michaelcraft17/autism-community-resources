import json, os, re, time
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
RETRY_CHECKPOINT = f"{SP}/new_sources_geocode_retry2_checkpoint.jsonl"

PO_BOX_RE = re.compile(r"^\s*P\.?\s*O\.?\s*Box", re.I)
STATE_ABBR = {"AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
              "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
              "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC","PW","GU","AS","MP","PR","VI"}

def load_latest(path):
    latest = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            latest[d["_uid"]] = d["coordinates"]
    return latest

def append(path, uid, coords):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"_uid": uid, "coordinates": coords}, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

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

def nominatim(query, countrycodes="us"):
    try:
        params = {"q": query, "format": "json", "limit": 1}
        if countrycodes:
            params["countrycodes"] = countrycodes
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
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

def build_candidates(name, addr):
    """Yield a sequence of (query_string, use_census) fallback attempts, best-effort ordered."""
    addr = addr.strip()
    parts = [p.strip() for p in addr.split(",")]

    # 4+ comma segments: drop middle suite/floor/room segments, keep street + last 2
    if len(parts) >= 4:
        cleaned = f"{parts[0]}, {parts[-2]}, {parts[-1]}"
        yield (cleaned, True)
        yield (cleaned + ", USA", False)

    # PO Box: drop to city/state only
    if PO_BOX_RE.match(parts[0]) if parts else False:
        if len(parts) >= 2:
            city_state = ", ".join(parts[-2:])
            yield (city_state + ", USA", False)

    # malformed "City, ST ZIP" 2-part where our earlier parser mishandled it
    if len(parts) == 2:
        tail_tokens = parts[1].split()
        if len(tail_tokens) == 2 and tail_tokens[0].upper() in STATE_ABBR:
            yield (addr + ", USA", False)

    # bare state name / vague region (ASAN)
    if len(parts) == 1:
        yield (addr + ", USA", False)

    # best-buddies style: retry using the school/org NAME + city/state instead of street address
    # name often like "Higley High School (Gilbert, AZ)"
    m = re.search(r"\(([^,]+),\s*([A-Z]{2})\)\s*$", name)
    if m and len(parts) >= 2:
        base_name = name[:m.start()].strip()
        city, state = m.group(1), m.group(2)
        yield (f"{base_name}, {city}, {state}, USA", False)

    # last resort: full raw address as-is via nominatim
    yield (addr + ", USA", False)

if __name__ == "__main__":
    ck = load_latest(CHECKPOINT)
    retry_ck = load_latest(RETRY_CHECKPOINT)

    nulls = []
    for source, path in SOURCES.items():
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                uid = f"{source}:{i}"
                if uid in ck and ck[uid] is None:
                    nulls.append((uid, d["name"], d["address"]))

    todo = [x for x in nulls if x[0] not in retry_ck]
    print(f"Total nulls: {len(nulls)}, already retried: {len(nulls) - len(todo)}, todo: {len(todo)}", flush=True)

    fixed = 0
    for i, (uid, name, addr) in enumerate(todo):
        result = None
        for query, use_census in build_candidates(name, addr):
            c = census_single(query) if use_census else None
            if not c:
                c = nominatim(query, countrycodes="us,pw")
                time.sleep(1.05)
            if c:
                result = c
                break
        append(RETRY_CHECKPOINT, uid, result)
        if result:
            fixed += 1
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(todo)} processed, fixed so far: {fixed}", flush=True)

    print(f"DONE. fixed {fixed}/{len(todo)} this run.", flush=True)
