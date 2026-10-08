#!/usr/bin/env python3
"""Rebuild community_resources.json (the flat working file the merge/fix tools read and write)
from the committed shards in data/. Use this after a fresh clone, before running any tool that
edits community_resources.json; run tools/split_by_region.py afterwards to write changes back.

    python3 tools/join_regions.py            # refuses to overwrite an existing file
    python3 tools/join_regions.py --force    # overwrite it
"""
import json
import os
import sys

OUT = "community_resources.json"
DATA_DIR = "data"


def main():
    if os.path.exists(OUT) and "--force" not in sys.argv:
        sys.exit(f"{OUT} already exists; pass --force to overwrite it from data/.")
    with open(os.path.join(DATA_DIR, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    entries = []
    for item in manifest["files"]:
        with open(os.path.join(DATA_DIR, item["file"]), encoding="utf-8") as f:
            part = json.load(f)
        assert len(part) == item["count"], f"{item['file']}: manifest says {item['count']}, found {len(part)}"
        entries.extend(part)
    assert len(entries) == manifest["total"], "manifest total does not match shard contents"
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)
    print(f"Wrote {OUT}: {len(entries)} entries from {len(manifest['files'])} shards.")


if __name__ == "__main__":
    main()
