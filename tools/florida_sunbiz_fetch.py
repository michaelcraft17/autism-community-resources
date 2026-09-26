#!/usr/bin/env python3
"""
Florida: Division of Corporations bulk non-profit data (round-3 research, C1).

Source: sftp.floridados.gov, user "Public", password "PubAccess1845!" --
published by the Florida Division of Corporations on its own data-downloads
page (https://dos.fl.gov/sunbiz/other-services/data-downloads/) as the
official free public bulk-distribution channel. This is the same category as
Sweden's open bulk file, not a bypassed control.

Download first:
    curl --insecure -u 'Public:PubAccess1845!' \\
        sftp://sftp.floridados.gov/Public/doc/Quarterly/Non-Profit/npcordata.zip \\
        -o /tmp/florida_scratch/npcordata.zip
    unzip -o /tmp/florida_scratch/npcordata.zip -d /tmp/florida_scratch

Fixed-width record layout (verified empirically against the actual files --
the server's own cornp/readme.txt is dated 2006 and documents a shorter
1170-char record; the current files are 1440 chars, but the leading fields
line up with the same layout, just extended):
    doc_number   [0:12]
    name         [12:204]
    status       [204:205]   'A' active / 'I' inactive
    filing_type  [205:220]   DOMNP/FORNP/NPREG = non-profit; others skipped
    address1     [220:262]
    address2     [262:304]
    city         [304:332]
    state        [332:334]
    zip          [334:344]
    country      [344:346]

Geocoding is a separate, explicit step (run after this, so it doesn't collide
with any other concurrent Nominatim consumer): see geocode_new_sources.py's
pattern, or run this module's --geocode flag.
"""
import glob
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from category_map import classify

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH_GLOB = "/tmp/florida_scratch/npcordata*.txt"
OUT_AUTISM = os.path.join(REPO, "new_resources_florida_autism.json")
OUT_DISABILITY = os.path.join(REPO, "new_resources_florida_disability.json")

NP_FILING_TYPES = {"DOMNP", "FORNP", "NPREG"}

AUTISM_RE = re.compile(r"\bautis|asperger", re.IGNORECASE)
DISABILITY_RE = re.compile(
    r"\bdisabilit|special needs|developmental(ly)? disabl|down syndrome|"
    r"cerebral palsy|\bdeaf\b|\bblind\b|intellectual disabilit",
    re.IGNORECASE,
)
UA = {"User-Agent": "autism-community-resources research (contact: changcheng875@gmail.com)"}


def parse_record(line):
    if len(line) < 346:
        return None
    name = line[12:204].strip()
    status = line[204:205]
    filing_type = line[205:220].strip()
    addr1 = line[220:262].strip()
    addr2 = line[262:304].strip()
    city = line[304:332].strip()
    state = line[332:334].strip()
    zip5 = line[334:344].strip()
    return {
        "doc_number": line[0:12].strip(),
        "name": name,
        "status": status,
        "filing_type": filing_type,
        "addr1": addr1,
        "addr2": addr2,
        "city": city,
        "state": state,
        "zip": zip5,
    }


def build_entry(rec, disability_scope):
    addr_parts = [rec["addr1"]]
    if rec["addr2"]:
        addr_parts.append(rec["addr2"])
    addr_parts += [rec["city"], f"{rec['state']} {rec['zip']}".strip()]
    full_addr = ", ".join(p for p in addr_parts if p)
    entry = {
        "name": rec["name"].title() if rec["name"].isupper() else rec["name"],
        "address": full_addr,
        "phone": "",
        "website": "",
        "type": classify(rec["name"], None),
        "source": "Florida Division of Corporations (Sunbiz) non-profit bulk data - official state open data",
        "services": [],
        "description": f"Registered Florida non-profit corporation ({rec['filing_type']})",
        "external_id": rec["doc_number"],
        "placeless": True,  # geocoded separately
    }
    if disability_scope:
        entry["disability_scope"] = disability_scope
    return entry


def main():
    files = sorted(glob.glob(SCRATCH_GLOB))
    if not files:
        print(f"ERROR: no files matching {SCRATCH_GLOB}. Download first (see docstring).")
        sys.exit(1)

    autism_out, disability_out = [], []
    total = 0
    seen_doc = set()
    for path in files:
        with open(path, encoding="latin-1") as f:
            for line in f:
                total += 1
                rec = parse_record(line.rstrip("\n"))
                if not rec or rec["status"] != "A" or rec["filing_type"] not in NP_FILING_TYPES:
                    continue
                if rec["doc_number"] in seen_doc:
                    continue
                is_autism = bool(AUTISM_RE.search(rec["name"]))
                is_disability = (not is_autism) and bool(DISABILITY_RE.search(rec["name"]))
                if not (is_autism or is_disability):
                    continue
                seen_doc.add(rec["doc_number"])
                if is_autism:
                    autism_out.append(build_entry(rec, None))
                else:
                    disability_out.append(build_entry(rec, "general"))

    print(f"Scanned {total} records across {len(files)} files.")
    print(f"Autism-named, active non-profit: {len(autism_out)}")
    print(f"Disability-named, active non-profit: {len(disability_out)}")

    with open(OUT_AUTISM, "w", encoding="utf-8") as f:
        json.dump(autism_out, f, ensure_ascii=False)
    with open(OUT_DISABILITY, "w", encoding="utf-8") as f:
        json.dump(disability_out, f, ensure_ascii=False)
    print(f"Wrote {OUT_AUTISM} and {OUT_DISABILITY}")


def _nominatim(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "limit": 1, "countrycodes": "us"}
    )
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
        return {"lat": float(data[0]["lat"]), "lng": float(data[0]["lon"])} if data else None
    except Exception:
        return None


def geocode_file(path):
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)
    cache = {}
    for i, e in enumerate(entries):
        q = e["address"] + ", USA"
        if q not in cache:
            cache[q] = _nominatim(q)
            time.sleep(1.05)
        coords = cache[q]
        if coords:
            e["coordinates"] = coords
            e["placeless"] = False
        if i % 25 == 0:
            print(f"  geocoded {i}/{len(entries)}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)
    print(f"Re-wrote {path} with coordinates.")


CITY_STATE_RE = re.compile(r",\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s+\d{5}")


def geocode_fallback_city(path):
    """Second pass: full-street-address Nominatim lookups miss a lot of real
    US addresses (TIGER/Line coverage gaps, common on residential streets --
    confirmed by hand on several failed Florida addresses that are perfectly
    well-formed). Retry city+state for anything still placeless -- coarser,
    but the site already supports placeless-vs-city-level entries and this
    beats leaving ~50% of a real source unmapped."""
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)
    cache = {}
    changed = 0
    for e in entries:
        if e.get("coordinates"):
            continue
        m = CITY_STATE_RE.search(e.get("address", ""))
        if not m:
            continue
        q = f"{m.group(1).strip()}, {m.group(2)}, USA"
        if q not in cache:
            cache[q] = _nominatim(q)
            time.sleep(1.05)
        coords = cache[q]
        if coords:
            e["coordinates"] = coords
            e["placeless"] = False
            changed += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)
    print(f"City-level fallback: {changed} more entries geocoded in {path}.")


if __name__ == "__main__":
    if "--geocode" in sys.argv:
        geocode_file(OUT_AUTISM)
        geocode_file(OUT_DISABILITY)
    elif "--geocode-fallback" in sys.argv:
        geocode_fallback_city(OUT_AUTISM)
        geocode_fallback_city(OUT_DISABILITY)
    else:
        main()
