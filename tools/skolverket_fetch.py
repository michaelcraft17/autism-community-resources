#!/usr/bin/env python3
"""
Sweden: special schools from Skolverket's Skolenhetsregistret (school-unit register), keyless JSON:

    https://api.skolverket.se/skolenhetsregistret/v2/school-units            list (code, name, status)
    https://api.skolverket.se/skolenhetsregistret/v2/school-units/<code>     detail incl. WGS84 coordinates

(Header `Accept: application/json`; the v4 vendor media type returns 406.) Detail is fetched for every
AKTIV unit (~7,500 calls, 3 threads each pausing 0.1 s before a call, cached per unit in
tools/skolverket_scratch/detail.jsonl). Failed calls are retried in a second, sequential pass 1 s apart; a unit
whose call still fails is dropped and counted with rc.note_failure. A refusal (401/403/451), or 20 failed calls
in a row in the first pass (400/404 not counted), stops the calls and the run exits without writing output.

Core = unit with schoolType GRAN (grundsärskola), GYAN (gymnasiesärskola), SP (specialskola), or flagged
specialSupportSchool, or a hospital school. These serve pupils with intellectual disability, autism, hearing
or vision impairment, ... so rows are disability_scope "general". The register's `headMaster` (a named
person) and e-mail are never read. Coordinates come from the BESOKSADRESS (visiting address) block.

Writes new_resources_skolverket.json.
"""
import json
import os
import sys
import time
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
THREADS, PAUSE, RETRY_PAUSE = 3, 0.1, 1.0   # detail calls: workers, seconds before each call, before each retry
MAX_FAILS_IN_A_ROW = 20                      # the host is down or blocking us: stop calling


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

    stop = {"why": None, "run": 0}   # why calls stopped; failed calls in a row

    def one(code, pause=PAUSE, first_pass=True):
        if stop["why"]:
            return code, {"_error": "not called: " + stop["why"]}
        time.sleep(pause)
        try:
            d = rc.get_json(f"{BASE}/{code}", headers=HDR, timeout=60)["data"]["attributes"]
        except Exception as e:  # noqa: BLE001
            http = getattr(e, "code", None)
            if http in rc.REFUSAL_CODES:   # rc.get has recorded the refusal
                stop["why"] = f"HTTP {http} refusal at {code}"
            elif first_pass and http not in (400, 404, 410):   # retries of failed calls may well fail in a row
                stop["run"] += 1
                if stop["run"] >= MAX_FAILS_IN_A_ROW and not stop["why"]:
                    stop["why"] = f"{stop['run']} failed calls in a row, last {code}: {e!r}"
                    rc.note_failure("skolverket-detail", stop["why"])
            return code, {"_error": repr(e)}
        stop["run"] = 0
        return code, d

    failed, lost = [], []
    with open(cpath, "a", encoding="utf-8") as f:
        def store(code, d):
            if "_error" in d:
                return False
            cache[code] = d
            f.write(json.dumps({"code": code, "d": d}, ensure_ascii=False) + "\n")
            return True

        with ThreadPoolExecutor(THREADS) as ex:
            for i, (code, d) in enumerate(ex.map(one, todo), 1):
                if not store(code, d):
                    failed.append(code)
                if i % 500 == 0:
                    print(f"  {i}/{len(todo)}", flush=True)
        if failed and not stop["why"]:
            print(f"  retrying {len(failed)} failed detail calls one at a time", flush=True)
        for code in failed:
            code, d = one(code, RETRY_PAUSE, first_pass=False)
            if not store(code, d):
                lost.append((code, d["_error"]))
    if stop["why"]:
        sys.exit(f"Skolverket: detail calls stopped ({stop['why']}) -- nothing written")
    for code, err in lost:
        rc.note_failure("skolverket-detail", f"{code}: {err}")
    if lost:
        print(f"  WARNING: {len(lost)} active units dropped, their detail call failed twice (rc.note_failure)")

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
