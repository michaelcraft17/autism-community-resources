import json, os, time
import requests

SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
RETRY_CHECKPOINT = f"{SP}/new_sources_geocode_retry2_checkpoint.jsonl"

# uid -> (query to try) or None to explicitly confirm "leave null, genuinely unlocatable"
MANUAL = {
    "asan-affiliate:0": None,  # "United States (nationwide, virtual)" - no location, correct to leave null
    "cpir-pti:23": "2196 Main St, Dunedin, FL 34698, USA",
    "cpir-pti:36": "Augusta, ME 04338, USA",
    "cpir-pti:87": "99 Edmiston Way, Buckhannon, WV 26201, USA",
    "ecta-partc:8": "410 Federal Street, Dover, DE 19901, USA",
    "ecta-partc:21": "Augusta, ME 04333, USA",
    "ecta-partc:34": "Empire State Plaza, Albany, NY 12237, USA",
    "ecta-partc:39": "2500 North Lincoln Boulevard, Oklahoma City, OK 73105, USA",
    "special-olympics:12": "Ewa Beach, HI 96706, USA",
    "special-olympics:26": "Jefferson City, MO 65101, USA",
    "special-olympics:31": "Lawrenceville, NJ 08648, USA",
    "special-olympics:34": "2200 Gateway Centre Boulevard, Morrisville, NC 27560, USA",
    "best-buddies:764": "Makawao, HI 96768, USA",
    "best-buddies:1262": "Gambrills, MD 21054, USA",
    "best-buddies:2692": None,  # "DC and Northern Virginia" - spans a whole metro region, no single point
}

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
    fixed = 0
    for uid, query in MANUAL.items():
        if query is None:
            with open(RETRY_CHECKPOINT, "a", encoding="utf-8") as f:
                f.write(json.dumps({"_uid": uid, "coordinates": None}, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            print(f"{uid}: confirmed unlocatable, left null")
            continue
        c = nominatim(query)
        with open(RETRY_CHECKPOINT, "a", encoding="utf-8") as f:
            f.write(json.dumps({"_uid": uid, "coordinates": c}, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        print(f"{uid}: {query} -> {c}")
        if c:
            fixed += 1
        time.sleep(1.05)
    print(f"DONE. fixed {fixed}/{sum(1 for v in MANUAL.values() if v is not None)}")
