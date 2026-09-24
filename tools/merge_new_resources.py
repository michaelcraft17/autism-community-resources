#!/usr/bin/env python3
"""
Merge every tools/../new_resources_*.json file in the repo root into
community_resources.json, deduping against the existing dataset and across the
new files themselves by normalized name and website domain.

Usage:
    python3 tools/merge_new_resources.py

After running, regenerate community_data.js:
    node gen_community_data.js
"""
import glob
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PATH = os.path.join(REPO, "community_resources.json")


def norm_name(name):
    # Unicode-aware: str.isalnum() recognizes non-Latin letters (Cyrillic,
    # Greek, CJK, ...) too, unlike an ASCII-only [^a-z0-9] regex, which
    # silently collapsed every non-Latin-script name to an empty or
    # near-empty key -- confirmed to have dropped real, distinct
    # organizations as false "duplicates" for both Ukraine (Cyrillic) and
    # Cyprus (Greek) entries before this fix.
    return "".join(c for c in (name or "").lower() if c.isalnum())


def norm_domain(url):
    if not url:
        return None
    m = re.search(r"^(?:https?://)?(?:www\.)?([^/]+)", url.strip())
    return m.group(1).lower() if m else None


def main():
    with open(MAIN_PATH, encoding="utf-8") as f:
        main_data = json.load(f)
    print(f"Existing entries: {len(main_data)}")

    seen_names = {norm_name(r.get("name")) for r in main_data}
    seen_domains = {norm_domain(r.get("website")) for r in main_data if r.get("website")}
    seen_domains.discard(None)

    files = sorted(glob.glob(os.path.join(REPO, "new_resources_*.json")))
    added_total = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
        added = 0
        skipped = 0
        for e in entries:
            n = norm_name(e.get("name"))
            d = norm_domain(e.get("website"))
            if n in seen_names or (d and d in seen_domains):
                skipped += 1
                continue
            main_data.append(e)
            seen_names.add(n)
            if d:
                seen_domains.add(d)
            added += 1
        added_total += added
        print(f"{os.path.basename(path)}: {added} added, {skipped} skipped as duplicates")

    with open(MAIN_PATH, "w", encoding="utf-8") as f:
        json.dump(main_data, f, ensure_ascii=False)

    print(f"\nTotal added: {added_total}")
    print(f"New total entries: {len(main_data)}")


if __name__ == "__main__":
    main()
