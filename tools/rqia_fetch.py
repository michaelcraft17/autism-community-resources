#!/usr/bin/env python3
"""
Northern Ireland -- RQIA (Regulation and Quality Improvement Authority) register of regulated services, open data
(Open Government Licence), OpenDataNI:
    https://admin.opendatani.gov.uk/dataset/8c94d33e-4c4e-47a9-8709-98af8ffa7462/resource/d8545f26-8772-4cc6-bdd2-f2c37076eeed/download/opendata.xlsx

Core: services whose "Categories of Care" include a learning-disability category (e.g. NH-LD, RC-LD, DCS-LD, SL-LD /
"LD", "LD(E)"). Service Name ends in "(<registration id>)", which is the stable id. The Current Manager column is
a personal name and is never read. Locations: full postcode via postcodes.io (ONS centroid; outward-code centroid when unknown).
Output: new_resources_rqia.json
"""
import os
import re
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402
from oscr_fetch import postcode_lookup, norm_pc, smart  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "rqia_scratch")
URL = "https://admin.opendatani.gov.uk/dataset/8c94d33e-4c4e-47a9-8709-98af8ffa7462/resource/d8545f26-8772-4cc6-bdd2-f2c37076eeed/download/opendata.xlsx"
SOURCE = "Northern Ireland RQIA register of regulated services (open data)"
LD_RE = re.compile(r"-LD\b|-LD\(E\)|\bLD\b")


def main():
    path = rc.download(URL, os.path.join(SCRATCH, "opendata.xlsx"))
    wb = openpyxl.load_workbook(path, read_only=True)
    rows = [list(r) + [None] * (14 - len(r)) for r in wb.active.iter_rows(values_only=True)]
    h = next(i for i, r in enumerate(rows) if r[0] == "Service Name")
    sel = [r for r in rows[h + 1:] if r[0] and r[9] and LD_RE.search(str(r[9]))]
    look, failed = postcode_lookup([norm_pc(r[5]) for r in sel if r[5]])
    entries, nogeo = [], 0
    for r in sel:
        m = re.match(r"(.*?)[\s\xa0]*\((\d+)\)\s*$", str(r[0]))
        if not m:
            print(f"  no id in {r[0]!r}, skipped")
            continue
        name, rid = rc.clean(m.group(1)), m.group(2)
        pc = norm_pc(r[5] or "")
        if pc in failed:
            rc.note_failure("postcodes.io", f"{rid}: {failed[pc]}")
            continue
        hit = look.get(pc)
        if not hit or not rc.plausible("GB", *hit):
            nogeo += 1
            continue
        stype = rc.clean(r[7])
        low = stype.lower()
        if "nursing" in low:
            services, typ = ["Nursing homes", "Residential & Social Care"], "social"
        elif "residential" in low:
            services, typ = ["Residential homes", "Residential & Social Care"], "social"
        elif "supported living" in low or "shared lives" in low or "placement" in low:
            services, typ = ["Supported living", "Residential & Social Care"], "social"
        elif "day" in low:
            services, typ = ["Day Programs", "Residential & Social Care"], "social"
        else:
            services, typ = ["Home-Based Support", "Information & Support"], "general_support"
        addr = ", ".join(x for x in (smart(rc.clean(r[k])) for k in (1, 2, 3, 4) if r[k]) if x)
        addr = f"{addr}, {pc}" if addr else pc
        prov = rc.clean(r[12])
        desc = f"RQIA regulated {stype.lower() or 'service'} ({rid}) registered for learning disability" + (f", provided by {prov}" if prov else "") + "."
        phone = re.sub(r"\D", "", str(r[6] or ""))
        entries.append(rc.entry(smart(name), SOURCE, typ, services, desc, address=addr, phone=phone or None,
                                lat=hit[0], lng=hit[1], external_id=f"rqia:{rid}", scope="general"))
    print(f"{len(sel)} learning-disability services; {nogeo} without a geocode")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_rqia.json"), entries)
    rc.spot_check(out, 20, fields=("name", "address", "type"))


if __name__ == "__main__":
    main()
