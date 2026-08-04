import json, re, os, sys

COMMIT = "--commit" in sys.argv

REPO = "C:/Users/Lenovo/autism-community-resources"
SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"

DEFAULT_SUGGESTED = {
    "free_services": False, "telehealth": False, "in_home": False,
    "accepts_medicaid": False, "early_intervention": False,
    "bilingual": False, "wheelchair_accessible": False,
}

FIELD_ORDER = ["name", "address", "phone", "website", "type", "source",
               "services", "description", "coordinates", "suggested", "npi_number"]

def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

def load_checkpoint(path):
    latest = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        latest[d["_uid"]] = d["coordinates"]
    return latest

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

GEOCODED_SOURCES = [
    ("asan-affiliate", f"{SP}/asan_affiliates.jsonl"),
    ("cpir-pti", f"{SP}/cpir_pti.jsonl"),
    ("ecta-partc", f"{SP}/ecta_partc.jsonl"),
    ("special-olympics", f"{SP}/special_olympics.jsonl"),
    ("best-buddies", f"{SP}/best_buddies.jsonl"),
]
SIBSHOPS_PATH = f"{SP}/sibshops_clean.jsonl"

if __name__ == "__main__":
    existing = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))
    print(f"Existing entries: {len(existing)}")
    existing_keys = {norm_key(e["name"], e["address"]) for e in existing}

    ck1 = load_checkpoint(f"{SP}/new_sources_geocode_checkpoint.jsonl")
    ck2 = load_checkpoint(f"{SP}/new_sources_geocode_retry2_checkpoint.jsonl")

    added_by_source = {}
    added_by_type = {}
    skipped_no_coords = 0
    skipped_dupe = 0
    new_entries = []
    seen_this_run = set()

    for source, path in GEOCODED_SOURCES:
        entries = load_jsonl(path)
        added = 0
        for i, e in enumerate(entries):
            uid = f"{source}:{i}"
            if not e.get("coordinates"):
                e = dict(e)
                e["coordinates"] = ck2.get(uid) or ck1.get(uid)
            if not e.get("coordinates"):
                skipped_no_coords += 1
                continue
            key = norm_key(e["name"], e["address"])
            if key in existing_keys or key in seen_this_run:
                skipped_dupe += 1
                continue
            seen_this_run.add(key)

            e = dict(e)
            e.pop("_uid", None)
            if "suggested" not in e:
                e["suggested"] = dict(DEFAULT_SUGGESTED)
            e = order_entry(e)
            new_entries.append(e)
            added += 1
            added_by_type[e["type"]] = added_by_type.get(e["type"], 0) + 1
        added_by_source[source] = added
        print(f"{source}: {added} added (of {len(entries)})")

    # sibshops: already has real coordinates from source, no street address text provided.
    # Address-based norm_key would collapse distinct branches sharing a generic name
    # (e.g. multiple "Sibshops" in different cities), so key on name + rounded coordinates instead.
    entries = load_jsonl(SIBSHOPS_PATH)
    added = 0
    for e in entries:
        if not e.get("coordinates"):
            skipped_no_coords += 1
            continue
        if e["address"]:
            key = norm_key(e["name"], e["address"])
        else:
            c = e["coordinates"]
            key = (re.sub(r'[^a-z0-9]', '', e["name"].lower()), round(c["lat"], 3), round(c["lng"], 3))
        if key in existing_keys or key in seen_this_run:
            skipped_dupe += 1
            continue
        seen_this_run.add(key)
        e = dict(e)
        if "suggested" not in e:
            e["suggested"] = dict(DEFAULT_SUGGESTED)
        e = order_entry(e)
        new_entries.append(e)
        added += 1
        added_by_type[e["type"]] = added_by_type.get(e["type"], 0) + 1
    added_by_source["sibshops"] = added
    print(f"sibshops: {added} added (of {len(entries)})")

    print(f"\nSkipped (no coordinates): {skipped_no_coords}")
    print(f"Skipped (duplicate of existing or within-run): {skipped_dupe}")
    print(f"Total new entries to add: {len(new_entries)}")
    print(f"By source: {added_by_source}")
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
