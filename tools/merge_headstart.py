import json, re, os, sys

COMMIT = "--commit" in sys.argv

REPO = "C:/Users/Lenovo/autism-community-resources"
SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
SRC = f"{SP}/head_start.jsonl"

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

if __name__ == "__main__":
    existing = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))
    print(f"Existing entries: {len(existing)}")
    existing_keys = {norm_key(e["name"], e["address"]) for e in existing}

    entries = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]

    # Multiple CSV rows can represent the same physical building offering both Head Start
    # and Early Head Start (same name+address, different program_type) - merge their
    # services lists into one entry per physical location instead of dropping the extras.
    by_key = {}
    skipped_dupe_existing = 0
    order = []
    for e in entries:
        key = norm_key(e["name"], e["address"])
        if key in existing_keys:
            skipped_dupe_existing += 1
            continue
        if key in by_key:
            for svc in e["services"]:
                if svc not in by_key[key]["services"]:
                    by_key[key]["services"].append(svc)
            combined = " / ".join(by_key[key]["services"])
            # description started with the single program label - replace it with the
            # combined label now that this location is known to offer more than one
            for old_svc in ["Head Start", "Early Head Start"]:
                if by_key[key]["description"].startswith(old_svc + " location"):
                    by_key[key]["description"] = by_key[key]["description"].replace(
                        old_svc + " location", combined + " location", 1)
                    break
        else:
            by_key[key] = dict(e)
            order.append(key)

    new_entries = [order_entry(by_key[k]) for k in order]
    added = len(new_entries)
    merged_locations = len(entries) - skipped_dupe_existing - added

    print(f"head-start: {added} unique physical locations added (of {len(entries)} CSV rows)")
    print(f"  {skipped_dupe_existing} skipped as duplicates of existing dataset entries")
    print(f"  {merged_locations} rows merged into an existing location's services list "
          f"(same building, multiple program types)")

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
