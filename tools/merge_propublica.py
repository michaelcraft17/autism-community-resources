import json, re, os, sys

COMMIT = "--commit" in sys.argv

REPO = "C:/Users/Lenovo/autism-community-resources"
SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
SRC = f"{SP}/propublica_autism.jsonl"

FIELD_ORDER = ["name", "address", "phone", "website", "type", "source",
               "services", "description", "coordinates", "suggested", "npi_number"]

def norm_key(name, address):
    n = re.sub(r'[^a-z0-9]', '', name.lower())
    street = address.split(",")[0]
    s = re.sub(r'[^a-z0-9]', '', street.lower())
    return (n, s)

def order_entry(e):
    out = {}
    for k in FIELD_ORDER:
        if k in e:
            out[k] = e[k]
    for k in e:
        if k not in out:
            out[k] = e[k]
    return out

def load_latest(path):
    latest = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        latest[d["_uid"]] = d["coordinates"]
    return latest

if __name__ == "__main__":
    existing = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))
    print(f"Existing entries: {len(existing)}")
    existing_keys = {norm_key(e["name"], e["address"]) for e in existing}

    # also dedupe against the still-staged (not yet committed) Head Start batch
    hs_path = f"{SP}/head_start.jsonl"
    if os.path.exists(hs_path):
        for line in open(hs_path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            existing_keys.add(norm_key(e["name"], e["address"]))

    ck1 = load_latest(f"{SP}/propublica_geocode_checkpoint.jsonl")
    ck2 = load_latest(f"{SP}/propublica_geocode_retry2_checkpoint.jsonl")

    entries = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    added = 0
    skipped_no_coords = 0
    skipped_dupe = 0
    seen_this_run = set()
    new_entries = []
    added_by_type = {}
    for i, e in enumerate(entries):
        uid = f"propublica:{i}"
        coords = ck1.get(uid) or ck2.get(uid)
        if not coords:
            skipped_no_coords += 1
            continue
        e = dict(e)
        e["coordinates"] = coords
        key = norm_key(e["name"], e["address"])
        if key in existing_keys or key in seen_this_run:
            skipped_dupe += 1
            continue
        seen_this_run.add(key)
        new_entries.append(order_entry(e))
        added += 1
        added_by_type[e["type"]] = added_by_type.get(e["type"], 0) + 1

    print(f"propublica-irs-autism: {added} added (of {len(entries)})")
    print(f"skipped (no coordinates): {skipped_no_coords}")
    print(f"skipped (duplicate of existing/head-start/within-run): {skipped_dupe}")
    print(f"By type: {added_by_type}")

    merged = existing + new_entries
    if not COMMIT:
        print("\n[DRY RUN] Not writing. Re-run with --commit to write community_resources.json.")
    else:
        tmp = f"{REPO}/community_resources.json.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, f"{REPO}/community_resources.json")
        print(f"\nWrote community_resources.json: {len(merged)} total entries")
