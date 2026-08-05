import json, os, time
import requests

SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
SRC = f"{SP}/propublica_autism.jsonl"
CK1 = f"{SP}/propublica_geocode_checkpoint.jsonl"
CK2 = f"{SP}/propublica_geocode_retry2_checkpoint.jsonl"

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
    entries = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    ck1 = load_latest(CK1)
    ck2 = load_latest(CK2)

    nulls = []
    for i, e in enumerate(entries):
        uid = f"propublica:{i}"
        if ck1.get(uid) is None:
            nulls.append((uid, e["name"], e["address"]))

    todo = [x for x in nulls if x[0] not in ck2]
    print(f"Total nulls: {len(nulls)}, already retried: {len(nulls)-len(todo)}, todo: {len(todo)}", flush=True)

    fixed = 0
    for i, (uid, name, addr) in enumerate(todo):
        parts = [p.strip() for p in addr.split(",")]
        # drop the street/PO-box segment, keep city + state/zip
        city_state = ", ".join(parts[-2:]) if len(parts) >= 2 else addr
        c = nominatim(city_state + ", USA")
        append(CK2, uid, c)
        if c:
            fixed += 1
        time.sleep(1.05)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(todo)}, fixed so far: {fixed}", flush=True)

    print(f"DONE. fixed {fixed}/{len(todo)}", flush=True)
