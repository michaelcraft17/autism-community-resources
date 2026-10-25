#!/usr/bin/env python3
"""
Wales -- Welsh Government "Address list of schools" (ODS, Open Government Licence v3), April 2026:
    https://www.gov.wales/sites/default/files/publications/2026-04/address-list-schools-values.ods
Core: maintained schools with Sector "Special" (day and boarding special schools). Broad: the PRU sheet (pupil referral
units, owner-approved). The 80 independent schools need a manual SEN check, so they are not built. Schools are premises: full-postcode ONS centroids
(postcodes.io). The workbook is read straight from its content.xml (no ODF library). Output: new_resources_wales_schools.json
"""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402
from oscr_fetch import postcode_lookup, norm_pc, smart  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "uk_schools_scratch")
URL = "https://www.gov.wales/sites/default/files/publications/2026-04/address-list-schools-values.ods"
SOURCE = "Wales Welsh Government address list of schools (special schools)"
PRU_SOURCE = "Wales Welsh Government address list of schools (pupil referral units)"
T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
P = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"


def sheet(root, name):
    for tb in root.iter(T + "table"):
        if tb.get(T + "name") == name:
            rows = []
            for tr in tb.iter(T + "table-row"):
                row = []
                for c in tr:
                    if c.tag in (T + "table-cell", T + "covered-table-cell"):
                        row += ["".join("".join(p.itertext()) for p in c.findall(P))] * min(int(c.get(T + "number-columns-repeated", "1")), 30)
                rows.append(row)
            return rows
    raise SystemExit(f"sheet {name} not found")


def main():
    path = os.path.join(SCRATCH, "wales.ods")
    if not os.path.exists(path):
        rc.download(URL, path)
    rc.STATUS["input"] = "gov.wales address-list-schools 2026-04"
    rows = sheet(ET.fromstring(zipfile.ZipFile(path).read("content.xml")), "Maintained")
    hdr = rows[0]
    ix = {h: i for i, h in enumerate(hdr)}
    sp = [r for r in rows[1:] if len(r) > 13 and r[ix["Sector"]] == "Special"]
    pru_rows = sheet(ET.fromstring(zipfile.ZipFile(path).read("content.xml")), "PRU")
    pru = [r for r in pru_rows[1:] if r[0].strip().isdigit()]
    jobs = [(r, ix, False) for r in sp] + [(r, {h: i for i, h in enumerate(pru_rows[0])}, True) for r in pru]
    look, failed = postcode_lookup([norm_pc(r[i["Postcode"]]) for r, i, _ in jobs if r[i["Postcode"]]])
    out, nogeo = [], 0
    for r, ix, is_pru in jobs:
        pc = norm_pc(r[ix["Postcode"]])
        if pc in failed:
            rc.note_failure("postcodes.io", f"{r[0]}: {failed[pc]}")
            continue
        hit = look.get(pc)
        if not hit or not rc.plausible("GB", *hit):
            nogeo += 1
            continue
        addr = ", ".join(x for x in (smart(rc.clean(r[ix[k]])) for k in ("Address 1", "Address 2", "Address 3", "Address 4")) if x) + f", {pc}"
        ph = re.sub(r"\s+", " ", rc.clean(r[ix["Phone Number"]]))
        if ph.upper() == "NULL" or re.sub(r"\D", "", ph).startswith("07"):  # missing, or a mobile number
            ph = ""
        if is_pru:
            out.append(rc.entry(smart(r[ix["School Name"]]), PRU_SOURCE, "education", ["Pupil referral unit", "Education"],
                                f"Pupil referral unit ({r[ix['Local Authority']]}): local-authority alternative provision for pupils who cannot attend a mainstream school, including some with additional learning needs. Welsh Government school number {r[0]}.",
                                address=addr, phone=ph or None, lat=hit[0], lng=hit[1], external_id=f"wales-school:{r[0]}", breadth="broad", scope="general"))
            continue
        out.append(rc.entry(smart(r[ix["School Name"]]), SOURCE, "education", ["Special education", "Education"],
                            f"Maintained special school ({r[ix['Local Authority']]}), Welsh Government school number {r[0]}.",
                            address=addr, phone=ph or None, lat=hit[0], lng=hit[1], external_id=f"wales-school:{r[0]}", scope="general"))
    print(f"{len(sp)} special schools, {len(pru)} PRUs; {nogeo} without a geocode")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_wales_schools.json"), out)
    rc.spot_check(fin, 10, fields=("name", "address", "type"))


if __name__ == "__main__":
    main()
