#!/usr/bin/env python3
"""
Bosnia and Herzegovina (new country shard BA) -- Zbirni e-registar udruzenja i fondacija, https://zbirniregistri.gov.ba/
(official collective register of associations and foundations: state, entity, canton and Brcko offices). Keyless JSON grid
endpoint behind a culture cookie: POST /Home/ReadNGOs, filter FullName~contains~'<keyword>'.

Core: active (not deleted, not in liquidation / in process) associations whose name matches a disability keyword. War-disabled
veterans' and work-injury / pension invalids' associations are broad and not built; "flautista" is a false hit for "autist".
AuthorizedPersonsList (named representatives) is never kept. Deduped on normalised name + municipality (two offices can list
the same association). Legal address geocoded with Nominatim (street + municipality, then municipality).
Output: new_resources_bosnia.json   Raw: tools/bosnia_scratch/ngos.json (reused if present)
"""
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "bosnia_scratch")
BASE = "https://zbirniregistri.gov.ba"
KEYS = ["autiz", "autist", "invalid", "posebnim", "teškoć", "poteškoć", "smetnj", "Down", "cerebral", "distrofi", "slijep", "gluh", "gluv",
        "nagluh", "paraplegi", "kvadripleg", "skleroz", "mentaln", "intelektual", "epilep", "dječije paraliz", "retard", "dislek", "ADHD", "hendikep"]
BROAD = re.compile(r"ratn|vojn|civiln|žrtv|branitelj|borac|borci|veteran|radni|rada\b|penzion|ranjen|stradal|demobilis|logoraš|šehid|poginul", re.I)
BAD = re.compile(r"flautist|ministarstvo|vlada\b|centar za socijalni", re.I)
SRC = "Bosnia and Herzegovina e-register of associations and foundations (zbirniregistri.gov.ba)"
AUTISM = re.compile(r"autiz|autist|asperger", re.I)


def fetch():
    path = os.path.join(SCRATCH, "ngos.json")
    if os.path.exists(path):
        return json.load(open(path))
    os.makedirs(SCRATCH, exist_ok=True)
    seen = {}
    for k in KEYS:
        body = urllib.parse.urlencode({"sort": "", "page": 1, "pageSize": 2000, "group": "", "filter": f"FullName~contains~'{k}'"}).encode()
        d = json.loads(rc.get(BASE + "/Home/ReadNGOs", data=body, method="POST", delay=1.0,
                              headers={"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}))
        for x in d["Data"]:
            x.pop("AuthorizedPersonsList", None)
            seen[x["Id"]] = x
        print(f"  {k}: {d['Total']} hits")
    json.dump(list(seen.values()), open(path, "w"), ensure_ascii=False)
    return list(seen.values())


def norm(s):
    return re.sub(r"[^a-z0-9ščćžđ]+", " ", s.lower()).strip()


def main():
    rows = fetch()
    rc.STATUS["input"] = "zbirniregistri.gov.ba ReadNGOs"
    live = [r for r in rows if r.get("IsActive") and not r.get("IsDeleted") and not r.get("IsInProcess") and not r.get("LiquidationDate")
            and not BAD.search(r["FullName"])]
    core, broad, seen = [], 0, set()
    for r in live:
        if BROAD.search(r["FullName"]) and not AUTISM.search(r["FullName"]):
            broad += 1
            continue
        key = (norm(r["FullName"]), norm(str(r.get("Municipality") or "")))
        if key in seen:
            continue
        seen.add(key)
        core.append(r)
    print(f"{len(rows)} hits; {len(live)} active; {len(core)} core after dedupe; {broad} broad skipped")
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="ba")
    out, nogeo = [], 0
    for r in core:
        mun = rc.clean(str(r.get("Municipality") or ""))
        mun = "" if mun.isdigit() else mun
        addr = rc.clean(r.get("FullAddress") or r.get("Address") or "")
        place = mun or (addr.split(",")[0] if "," in addr else "")
        hit = geoc.geocode(f"{addr}, {mun}, Bosna i Hercegovina" if addr else f"{mun}, Bosna i Hercegovina") if (addr or mun) else None
        hit = hit or (geoc.geocode(f"{place}, Bosna i Hercegovina") if place else None)
        if not hit or not rc.plausible("BA", *hit):
            nogeo += 1
            continue
        autism = bool(AUTISM.search(r["FullName"]))
        name = rc.clean(r["FullName"])
        out.append(rc.entry(name, SRC, "advocacy", ["Advocacy", "Information & Support"],
                            f"Registered association (registration no. {rc.clean(r['RegistrationNumber'])}, {rc.clean(r['RegisteredBy'])}) with a disability-related name.",
                            address=", ".join(x for x in (addr, mun if mun and mun not in addr else "", "Bosna i Hercegovina") if x),
                            lat=hit[0], lng=hit[1], external_id=f"ba-ngo:{r['Id']}", scope=None if autism else "general"))
    print(f"{len(out)} entries; {nogeo} without a geocode")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_bosnia.json"), out)
    rc.spot_check(fin, 20, fields=("name", "address"))


if __name__ == "__main__":
    main()
