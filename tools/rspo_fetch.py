#!/usr/bin/env python3
"""
Poland: special-education institutions from RSPO (Rejestr Szkol i Placowek Oswiatowych), the Ministry of
Education's register -- keyless JSON API behind https://rspo.gov.pl/ :

    POST https://rspo.gov.pl/api/Institution?PageOffset=<item offset>&PageSize=500     body: JSON filter
    GET  https://rspo.gov.pl/api/Institution/<rspo>                                  detail, with hqAddressGeotag

Two filters, unioned on the `rspo` id:
  {"specificityIdList": [1]}                                   specjalna (special) schools/kindergartens/classes
  {"institutionTypeIdList": [20,42,48,49,50,51,52,53,54]}      poradnie psychologiczno-pedagogiczne and specialist
        clinics (20,48,49), special vocational schools (42), SOSW (50), OREW (51), SOW (52), MOW (53), MOS (54)
Liquidated institutions are excluded by the API. Youth behavioural / socio-therapy centres (types 53, 54) are tagged
breadth "broad"; the rest is "core". `directorName/Surname` and `leadAuthorities[].firstName/surname` (which can be a
person) are never read; the operator is named only when it is a legal entity (name only).

Coordinates come from the detail call (about 5,000 calls, 3 threads each pausing 0.1 s before a call, cached per
id in tools/rspo_scratch/detail.jsonl). Failed calls are retried in a second, sequential pass 1 s apart; an
institution whose call still fails is dropped and counted with rc.note_failure. A refusal (401/403/451), or 20
failed calls in a row in the first pass (400/404 not counted), stops the calls and the run exits without writing
output.
The register's geotags are not always right (a Katowice street that shares a name
with Zielona Gora was tagged near Zielona Gora), so rows whose geotag is > 100 km from the median of the other
rows with the same postcode area are re-geocoded ("street nr, zip city, Poland", cached) and dropped if that does
not land back in the postcode area. The re-geocode first takes the coordinates the dataset already holds for the
row when its address is unchanged (rc.prior_coords), and only asks Nominatim otherwise.

Writes new_resources_rspo.json.
"""
import json
import math
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "rspo_scratch")
SOURCE = "Poland RSPO (Rejestr Szkol i Placowek Oswiatowych) - official education institution register"
API = "https://rspo.gov.pl/api/Institution"
FILTERS = [{"specificityIdList": [1]}, {"institutionTypeIdList": [20, 42, 48, 49, 50, 51, 52, 53, 54]}]
BROAD_TYPES = {53, 54}
CLINIC_TYPES = {20, 48, 49}
THREADS, PAUSE, RETRY_PAUSE = 3, 0.1, 1.0   # detail calls: workers, seconds before each call, before each retry
MAX_FAILS_IN_A_ROW = 20                      # the host is down or blocking us: stop calling


PL_SMALL = {"w", "we", "z", "ze", "i", "im", "na", "nr", "dla", "przy", "od", "do", "o", "oraz", "a", "po", "pod", "nad", "u"}
PL_KEEP = {"II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "LO", "SOSW", "SOW", "OREW", "MOW", "MOS", "ZS", "ZSS",
           "ZSO", "ZSP", "SP", "PPP", "SPZOZ", "PCK", "PCPR", "PTTK", "WSS", "SPZ", "TPD", "PSONI", "TPD", "RM", "CKU", "CKZIU", "ZSZ"}


def pl_title(s):
    """RSPO names are often ALL CAPS; title-case them, keep roman numerals/acronyms, lower-case small Polish words."""
    s = rc.clean(s)
    if not s.isupper():
        return s
    out = []
    for i, tok in enumerate(re.split(r"(\s+|-|\"|')", s)):
        if tok in PL_KEEP:
            out.append(tok)
        elif tok.lower() in PL_SMALL and i > 0:
            out.append(tok.lower())
        else:
            out.append(tok.capitalize())
    return "".join(out)


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111, (a[1] - b[1]) * 111 * math.cos(math.radians(a[0])))


def listing():
    items = {}
    for flt in FILTERS:
        off = 0
        while True:
            page = json.loads(rc.get(f"{API}?PageOffset={off}&PageSize=500", data=json.dumps(flt).encode(),
                                      headers={"Content-Type": "application/json"}, method="POST", timeout=120))
            for it in page["items"]:
                items[it["rspo"]] = it
            off += 500
            if off >= page["totalCount"]:
                break
        print(f"filter {flt}: running total {len(items)}")
    return items


def load_cache(path):
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                d = json.loads(line)
                out[d["id"]] = d["d"]
            except Exception:  # noqa: BLE001
                pass
    return out


def main():
    os.makedirs(SCRATCH, exist_ok=True)
    items = listing()
    cpath = os.path.join(SCRATCH, "detail.jsonl")
    cache = load_cache(cpath)
    todo = [i for i in items if i not in cache]
    print(f"{len(items)} institutions, {len(todo)} detail calls to make")

    stop = {"why": None, "run": 0}   # why calls stopped; failed calls in a row

    def one(i, pause=PAUSE, first_pass=True):
        if stop["why"]:
            return i, {"_error": "not called: " + stop["why"]}
        time.sleep(pause)
        try:
            d = rc.get_json(f"{API}/{i}", timeout=60, delay=0.0)
            keep = {k: d.get(k) for k in ("hqAddressGeotag", "hqAddressZipCode", "hqAddressPostal", "hqAddressStreet",
                                           "hqAddressBuildingNr", "hqAddressPremiseNr", "specificity", "publicStatus",
                                           "departmentTypeList", "isEmployingSpeechTherapist")}
        except Exception as e:  # noqa: BLE001
            http = getattr(e, "code", None)
            if http in rc.REFUSAL_CODES:   # rc.get has recorded the refusal
                stop["why"] = f"HTTP {http} refusal at {i}"
            elif first_pass and http not in (400, 404, 410):   # retries of failed calls may well fail in a row
                stop["run"] += 1
                if stop["run"] >= MAX_FAILS_IN_A_ROW and not stop["why"]:
                    stop["why"] = f"{stop['run']} failed calls in a row, last {i}: {e!r}"
                    rc.note_failure("rspo-detail", stop["why"])
            return i, {"_error": repr(e)}
        stop["run"] = 0
        return i, keep

    failed, lost = [], []
    with open(cpath, "a", encoding="utf-8") as f:
        def store(i, d):
            if "_error" in d:
                return False
            cache[i] = d
            f.write(json.dumps({"id": i, "d": d}, ensure_ascii=False) + "\n")
            return True

        with ThreadPoolExecutor(THREADS) as ex:
            for n, (i, d) in enumerate(ex.map(one, todo), 1):
                if not store(i, d):
                    failed.append(i)
                if n % 500 == 0:
                    print(f"  {n}/{len(todo)}", flush=True)
        if failed and not stop["why"]:
            print(f"  retrying {len(failed)} failed detail calls one at a time", flush=True)
        for i in failed:
            i, d = one(i, RETRY_PAUSE, first_pass=False)
            if not store(i, d):
                lost.append((i, d["_error"]))
    if stop["why"]:
        sys.exit(f"RSPO: detail calls stopped ({stop['why']}) -- nothing written")
    for i, err in lost:
        rc.note_failure("rspo-detail", f"{i}: {err}")
    if lost:
        print(f"  WARNING: {len(lost)} institutions dropped, their detail call failed twice (rc.note_failure)")

    rows = []
    for i, it in items.items():
        d = cache.get(i)
        if not d:
            continue
        zip_ = rc.clean(it.get("hqAddressZipCode"))
        street = rc.clean(it.get("hqAddressStreet"))
        nr = rc.clean(it.get("hqAddressBuildingNr")) + (f"/{rc.clean(it['hqAddressPremiseNr'])}" if rc.clean(it.get("hqAddressPremiseNr")) else "")
        city = rc.clean(it.get("hqAddressPostal")) or rc.clean((it.get("hqAddressLocality") or {}).get("name"))
        geo = d.get("hqAddressGeotag") or {}
        rows.append({"it": it, "zip": zip_, "street": street, "nr": nr, "city": city,
                     "lat": geo.get("latitude"), "lng": geo.get("longitude"), "area": zip_[:2] if re.match(r"\d\d-\d{3}", zip_) else None})

    # postcode-area medians for the geotag sanity check
    by_area = {}
    for r in rows:
        if r["area"] and rc.plausible("PL", r["lat"], r["lng"]):
            by_area.setdefault(r["area"], []).append(r)
    med = {a: (statistics.median(x["lat"] for x in rs), statistics.median(x["lng"] for x in rs)) for a, rs in by_area.items() if len(rs) >= 5}
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="pl")
    entries, regeo, dropped = [], 0, 0
    for r in rows:
        it = r["it"]
        lat, lng = r["lat"], r["lng"]
        addr = ", ".join(x for x in (f"{r['street']} {r['nr']}".strip(), f"{r['zip']} {r['city']}".strip()) if x)
        eid = f"rspo:{it['rspo']}"
        m = med.get(r["area"])
        ok = rc.plausible("PL", lat, lng) and (not m or km(m, (lat, lng)) <= 100)
        if not ok:
            q = f"{r['street']} {r['nr']}, {r['zip']} {r['city']}, Poland".replace("ul. ", "")
            # coordinates already in the dataset for this unchanged address, else Nominatim
            hit = rc.prior_coords(eid, addr) or geoc.geocode(q) or geoc.geocode(f"{r['zip']} {r['city']}, Poland")
            if hit and rc.plausible("PL", *hit) and (not m or km(m, hit) <= 100):
                lat, lng = hit
                regeo += 1
            else:
                dropped += 1
                continue
        tid = it["type"]["id"]
        tname = it["type"]["name"]
        clinic = tid in CLINIC_TYPES
        services = ["Special Education"] if not clinic else ["Information & Support", "Psychological Counselling"]
        if tid in (51,):
            services = ["Special Education", "Rehabilitation"]
        name = pl_title(it["name"])
        desc = tname + (f", ages/students: {it['studentsNr']}" if False else "") + "."
        if it.get("studentsNr"):
            desc = f"{tname}; {it['studentsNr']} pupils."
        lead = next((a["name"] for a in it.get("leadAuthorities") or [] if not a.get("surname") and re.search(r"[A-Za-z]{3}", a.get("name") or "")), None)
        if lead:
            desc += f" Run by {pl_title(lead)}."
        entries.append(rc.entry(name, SOURCE, "education" if not clinic else "general_support", services, desc, address=addr,
                                phone=it.get("telephone"), website=rc.clean_url(it.get("website")), lat=lat, lng=lng,
                                external_id=eid, breadth="broad" if tid in BROAD_TYPES else "core", scope="general"))
    print(f"RSPO: {len(entries)} entries ({regeo} re-geocoded after a bad geotag, {dropped} dropped)")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_rspo.json"), entries)
    rc.spot_check(out, 12, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
