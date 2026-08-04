import json

SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
SOURCES = {
    "asan-affiliate": f"{SP}/asan_affiliates.jsonl",
    "cpir-pti": f"{SP}/cpir_pti.jsonl",
    "ecta-partc": f"{SP}/ecta_partc.jsonl",
    "special-olympics": f"{SP}/special_olympics.jsonl",
    "best-buddies": f"{SP}/best_buddies.jsonl",
    "sibshops": f"{SP}/sibshops_clean.jsonl",
}

def load_checkpoint(path):
    latest = {}
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            latest[d["_uid"]] = d["coordinates"]
    except FileNotFoundError:
        pass
    return latest

ck1 = load_checkpoint(f"{SP}/new_sources_geocode_checkpoint.jsonl")
ck2 = load_checkpoint(f"{SP}/new_sources_geocode_retry2_checkpoint.jsonl")

def plausible(lat, lng):
    boxes = [
        (24, 50, -125, -66),     # continental US
        (51, 72, -180, -129),    # Alaska
        (18, 23, -161, -154),    # Hawaii
        (17, 19, -68, -64),      # PR/VI
        (13, 21, 144, 146),      # Guam/N.Mariana
        (-15, -13, -171, -169),  # American Samoa
        (6, 10, 134, 135),       # Palau
    ]
    return any(a <= lat <= b and c <= lng <= d for a, b, c, d in boxes)

bad = []
total = 0
nulls = 0
for source, path in SOURCES.items():
    for i, line in enumerate(open(path, encoding="utf-8")):
        d = json.loads(line)
        uid = f"{source}:{i}"
        coords = d.get("coordinates")
        if coords is None and source != "sibshops":
            coords = ck2.get(uid, ck1.get(uid))
        total += 1
        if not coords:
            nulls += 1
            continue
        lat, lng = coords["lat"], coords["lng"]
        if not plausible(lat, lng):
            bad.append((source, d["name"], d["address"], coords))

print(f"total entries checked: {total}, still null: {nulls}, implausible: {len(bad)}")
for source, name, addr, coords in bad:
    print(f" - [{source}] {name[:40]} | {addr} | {coords}")
