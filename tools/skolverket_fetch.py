#!/usr/bin/env python3
"""
Sweden: special schools from Skolverket's Skolenhetsregistret (school-unit register), keyless JSON:

    https://api.skolverket.se/skolenhetsregistret/v2/school-units            list (code, name, status)
    https://api.skolverket.se/skolenhetsregistret/v2/school-units/<code>     detail incl. WGS84 coordinates

(Header `Accept: application/json`; the v4 vendor media type returns 406.) Detail is fetched for every
AKTIV unit (~7,500 calls, 6 threads, cached per unit in tools/skolverket_scratch/detail.jsonl).

Core = unit with schoolType GRAN (grundsärskola), GYAN (gymnasiesärskola), SP (specialskola), or flagged
specialSupportSchool, or a hospital school. These serve pupils with intellectual disability, autism, hearing
or vision impairment, ... so rows are disability_scope "general". The register's `headMaster` (a named
person) and e-mail are never read. Coordinates come from the BESOKSADRESS (visiting address) block.

Writes new_resources_skolverket.json.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "skolverket_scratch")
SOURCE = "Sweden Skolverket Skolenhetsregistret - official school-unit register"
BASE = "https://api.skolverket.se/skolenhetsregistret/v2/school-units"
HDR = {"Accept": "application/json"}
CORE_TYPES = {"GRAN": "grundsärskola (compulsory school for pupils with intellectual disability)",
              "GYAN": "gymnasiesärskola (upper-secondary school for pupils with intellectual disability)",
              "SP": "specialskola (special school for pupils with hearing/vision impairment or deaf-blindness)"}


def load_cache(path):
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                d = json.loads(line)
                out[d["code"]] = d["d"]
            except Exception:  # noqa: BLE001
                pass
    return out


def main():
    os.makedirs(SCRATCH, exist_ok=True)
    units = rc.get_json(BASE, headers=HDR, timeout=120)["data"]["attributes"]
    active = [u["schoolUnitCode"] for u in units if u["status"] == "AKTIV"]
    cpath = os.path.join(SCRATCH, "detail.jsonl")
    cache = load_cache(cpath)
    todo = [c for c in active if c not in cache]
    print(f"{len(units)} units, {len(active)} active, {len(todo)} detail calls to make")

    def one(code):
        try:
            return code, rc.get_json(f"{BASE}/{code}", headers=HDR, timeout=60)["data"]["attributes"]
        except Exception as e:  # noqa: BLE001
            return code, {"_error": str(e)}

    with open(cpath, "a", encoding="utf-8") as f, ThreadPoolExecutor(6) as ex:
        for i, (code, d) in enumerate(ex.map(one, todo), 1):
            if "_error" not in d:
                cache[code] = d
                f.write(json.dumps({"code": code, "d": d}, ensure_ascii=False) + "\n")
            if i % 500 == 0:
                print(f"  {i}/{len(todo)}", flush=True)

    entries, nocoord, noncore = [], 0, 0
    for code in active:
        d = cache.get(code)
        if not d:
            continue
        types = set(d.get("schoolTypes") or [])
        hospital = any("sjukhus" in (d.get(k) or "").lower() for k in ("displayName", "schoolName"))
        special = d.get("specialSupportSchool")
        kinds = [CORE_TYPES[t] for t in ("GRAN", "GYAN", "SP") if t in types]
        if not (kinds or special or hospital):
            noncore += 1
            continue
        visit = next((a for a in d.get("addresses", []) if a.get("type") == "BESOKSADRESS"), None)
        gc = (visit or {}).get("geoCoordinates") or {}
        if not rc.plausible("SE", gc.get("latitude"), gc.get("longitude")):
            nocoord += 1
            continue
        addr = ", ".join(x for x in (rc.clean(visit.get("streetAddress")), f"{visit.get('postalCode', '')} {rc.clean(visit.get('locality'))}".strip()) if x)
        if special:
            kinds.append("special support school (specialpedagogiskt stöd)")
        if hospital and not kinds:
            kinds.append("hospital school")
        desc = "School unit offering " + "; ".join(kinds) + "."
        entries.append(rc.entry(d.get("displayName") or d.get("schoolName"), SOURCE, "education", ["Special Education"], desc,
                                address=addr, phone=d.get("phoneNumber"), website=rc.clean_url(d.get("url")),
                                lat=gc["latitude"], lng=gc["longitude"], external_id=f"skolverket:{code}", scope="general"))
    # drop rows whose coordinates sit far from the other units sharing their first two postcode digits
    # (the register has a few visiting addresses that disagree with their coordinates)
    import math
    import re
    import statistics
    groups = {}
    for e in entries:
        m = re.search(r"\b(\d{2})\d{3} ", e["address"])
        groups.setdefault(m[1] if m else None, []).append(e)
    far = set()
    for k, es in groups.items():
        if k is None or len(es) < 4:
            continue
        mla = statistics.median(e["coordinates"]["lat"] for e in es)
        mlo = statistics.median(e["coordinates"]["lng"] for e in es)
        for e in es:
            c = e["coordinates"]
            if math.hypot((c["lat"] - mla) * 111, (c["lng"] - mlo) * 111 * math.cos(math.radians(mla))) > 300:
                far.add(e["external_id"])
                print(f"  dropped (coordinates far from postcode area): {e['name']} | {e['address']}")
    entries = [e for e in entries if e["external_id"] not in far]
    print(f"Skolverket: {len(entries)} core, {nocoord} without coordinates, {noncore} mainstream units skipped")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_skolverket.json"), entries)
    rc.spot_check(out, 10, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
