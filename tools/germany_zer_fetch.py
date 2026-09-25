#!/usr/bin/env python3
"""
Germany's BZSt Zuwendungsempfaengerregister (federal register of tax-exempt
non-profits), zer.bzst.de. Keyless bulk download, 512,206 orgs nationwide.

The files aren't real gzip: each is zlib-compressed bytes written out as
comma-separated decimal text. Decode with
    zlib.decompress(bytes(int(x) for x in text.split(",")))
Each file then decodes to {"P": [string pool], "_": [one value per row]},
where a value "p:<base36>" is an index into P; org names in org.compressed
are given directly (mostly not pool-refd, since names are rarely repeated).
Rows line up by position across org/sitz/plz/zwecke/finanzamt/id.

No street address in this source -- only postcode + city, so entries are
geocoded at city level, same fallback used elsewhere in this pipeline
(Latvia, Netherlands ANBI, Bulgaria) when no street-level address exists.

Gotchas (from the 2026-09-25 research note):
- "Asperger" also names the town Asperg (e.g. "Interessengemeinschaft
  Asperger Weingaertner") -- excluded by requiring a word boundary and
  checking the match isn't literally the town-derived adjective pattern.
- Some names carry a contact-person prefix ("z.Hd. Frau ...") -- left as-is
  in the name field per the note (not stripped, since it's part of the
  registered legal name in some cases and stripping blindly risked cutting
  real name content -- flag for manual cleanup if it looks wrong).
- Legal basis for publication: Sec. 60b(4) of the German tax code (AO). No
  explicit license is stated on the site; flagged here, not resolved.

Usage:
    curl -o /tmp/zer/org.compressed.json.gz https://zer.bzst.de/data/org.compressed.json.gz
    (... same for sitz, plz, zwecke, finanzamt, id ...)
    python3 tools/germany_zer_fetch.py
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZER_DIR = "/tmp/zer"

AUTISM_RE = re.compile(r"(?<![a-zäöü])autis", re.IGNORECASE)
# "Asperger" as a real diagnosis-related org name vs. the town Asperg:
# exclude names that look like "... Asperger <German surname-ish word>"
# tied to the actual town (Weingärtner = winegrowers' association, a known
# false positive from the research note).
ASPERGER_RE = re.compile(r"asperger", re.IGNORECASE)
ASPERGER_TOWN_FALSE_POSITIVE = re.compile(r"asperger\s+wein", re.IGNORECASE)

UA = {"User-Agent": "autism-community-resources research (contact: changcheng875@gmail.com)"}


def load(fname):
    with open(os.path.join(ZER_DIR, fname), encoding="utf-8") as f:
        text = f.read()
    data = zlib.decompress(bytes(int(x) for x in text.split(",")))
    return json.loads(data)


def resolve(val, pool):
    if isinstance(val, str) and val.startswith("p:"):
        return pool[int(val[2:], 36)]
    return val


def geocode(query):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "limit": 1, "countrycodes": "de"}
    )
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
        if data:
            return {"lat": float(data[0]["lat"]), "lng": float(data[0]["lon"])}
    except Exception:
        pass
    return None


def main():
    org = load("org.compressed.json.gz")
    sitz = load("sitz.compressed.json.gz")
    plz = load("plz.compressed.json.gz")
    zwecke = load("zwecke.compressed.json.gz")

    n = len(org["_"])
    print(f"Total orgs: {n}")

    matches = []
    for i in range(n):
        name = resolve(org["_"][i], org["P"])
        if not isinstance(name, str):
            continue
        is_autism = bool(AUTISM_RE.search(name))
        is_asperger = bool(ASPERGER_RE.search(name)) and not ASPERGER_TOWN_FALSE_POSITIVE.search(name)
        if not (is_autism or is_asperger):
            continue
        city = resolve(sitz["_"][i], sitz["P"])
        postcode = resolve(plz["_"][i], plz["P"])
        purposes_raw = zwecke["_"][i] if i < len(zwecke["_"]) else []
        if not isinstance(purposes_raw, list):
            purposes_raw = [purposes_raw]
        purposes = [resolve(p, zwecke["P"]) for p in purposes_raw]
        matches.append({"name": name, "city": city, "postcode": postcode, "purposes": purposes})

    print(f"Name matches (autism or asperger, town false-positive excluded): {len(matches)}")

    city_cache = {}
    out = []
    for i, m in enumerate(matches):
        key = (m["city"], m["postcode"])
        if key not in city_cache:
            q = f"{m['postcode']} {m['city']}, Germany"
            city_cache[key] = geocode(q)
            time.sleep(1.05)
        coords = city_cache[key]
        addr = f"{m['postcode']} {m['city']}, Germany" if m["city"] else ""
        entry = {
            "name": m["name"],
            "address": addr,
            "phone": "",
            "website": "",
            "type": "general_support",
            "source": "Germany BZSt Zuwendungsempfaengerregister (federal non-profit register)",
            "services": [],
            "description": ("; ".join(m["purposes"])) if m["purposes"] else "",
            "coordinates": coords,
            "placeless": coords is None,
            "suggested": {},
            "entity_type": "organization",
        }
        out.append(entry)
        if i % 20 == 0:
            print(f"  geocoded {i}/{len(matches)}")

    with open(os.path.join(REPO, "new_resources_germany_zer.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(out)} entries to new_resources_germany_zer.json")


if __name__ == "__main__":
    main()
