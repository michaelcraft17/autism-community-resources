#!/usr/bin/env python3
"""
Drop registry rows (given external_id prefixes) whose website matches an older id-less entry AND whose name shares >= 60%
of its distinctive tokens. The merge script skips its domain rule for rows with an external_id (registries share sites),
so this catches the genuine duplicates of hand-collected rows. Usage: dedupe_registry_vs_manual.py oscr au-abn ...
"""
import collections
import json
import os
import re
import sys
import unicodedata
from urllib.parse import urlparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOP = {"the", "and", "inc", "ltd", "society", "association", "services", "service", "centre", "center", "les", "des", "for", "limited",
        "incorporated", "charitable", "trust", "foundation", "scotland", "scottish"}


def dom(u):
    return urlparse(u if "//" in u else "//" + u).netloc.lower().removeprefix("www.")


def toks(n):
    n = unicodedata.normalize("NFKD", n.lower())
    n = "".join(c for c in n if not unicodedata.combining(c))
    return {t for t in re.findall(r"[a-z0-9]{3,}", n) if t not in STOP}


def main(prefixes):
    path = os.path.join(REPO, "community_resources.json")
    d = json.load(open(path))
    old = collections.defaultdict(list)
    for e in d:
        if not e.get("external_id") and e.get("website"):
            old[dom(e["website"])].append(e)
    keep, n = [], collections.Counter()
    for e in d:
        p = str(e.get("external_id", "")).split(":")[0]
        if p in prefixes and e.get("website") and old.get(dom(e["website"])):
            t = toks(e["name"])
            if any(t and toks(o["name"]) and len(t & toks(o["name"])) / min(len(t), len(toks(o["name"]))) >= 0.6 for o in old[dom(e["website"])]):
                n[p] += 1
                continue
        keep.append(e)
    print(dict(n), len(d), "->", len(keep))
    json.dump(keep, open(path, "w"), ensure_ascii=False)


if __name__ == "__main__":
    main(set(sys.argv[1:]))
