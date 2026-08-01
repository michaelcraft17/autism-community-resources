import json, re, os, sys

COMMIT = "--commit" in sys.argv

REPO = "C:/Users/Lenovo/autism-community-resources"
SCRATCH = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"

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

if __name__ == "__main__":
    existing = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))
    print(f"Existing entries: {len(existing)}")
    existing_keys = {norm_key(e["name"], e["address"]) for e in existing}

    sources = [
        ("npi_specialty_geocoded.jsonl", "npi-registry-specialty"),
        ("ndrn_pa.jsonl", "ndrn-protection-advocacy"),
        ("aucd_ucedd.jsonl", "aucd-ucedd"),
        ("autism_care_network.jsonl", "autism-care-network"),
    ]

    added_by_source = {}
    added_by_type = {}
    skipped_no_coords = 0
    skipped_dupe = 0
    new_entries = []
    seen_this_run = set()

    for fname, label in sources:
        entries = load_jsonl(f"{SCRATCH}/{fname}")
        added = 0
        for e in entries:
            if not e.get("coordinates"):
                skipped_no_coords += 1
                continue
            key = norm_key(e["name"], e["address"])
            if key in existing_keys or key in seen_this_run:
                skipped_dupe += 1
                continue
            seen_this_run.add(key)

            e = dict(e)
            e.pop("_coords_approx_city_level", None)
            if "suggested" not in e:
                e["suggested"] = dict(DEFAULT_SUGGESTED)
            e = order_entry(e)
            new_entries.append(e)
            added += 1
            added_by_type[e["type"]] = added_by_type.get(e["type"], 0) + 1
        added_by_source[fname] = added
        print(f"{fname}: {added} added (of {len(entries)})")

    print(f"\nSkipped (no coordinates): {skipped_no_coords}")
    print(f"Skipped (duplicate of existing or within-run): {skipped_dupe}")
    print(f"Total new entries to add: {len(new_entries)}")
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
