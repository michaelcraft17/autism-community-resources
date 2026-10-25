#!/usr/bin/env python3
"""
Wales -- Welsh Government "Address list of schools" (ODS, Open Government Licence v3), April 2026:
    https://www.gov.wales/sites/default/files/publications/2026-04/address-list-schools-values.ods
Core: maintained schools with Sector "Special" (day and boarding special schools). Broad: the PRU sheet (pupil referral
units, owner-approved). Independent sheet: only the 23 schools hand-checked against Estyn (INDEP below; 17 core where autism is
a named main need, 6 broad for other additional learning needs). The other independent schools are not built. Schools are premises: full-postcode ONS centroids
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
INDEP_SOURCE = "Wales Welsh Government address list of schools (independent schools, SEN-checked)"
# school number -> (breadth, who the school is for per Estyn, checked 2026-10-25)
INDEP = {
    "6616022": ("core", "autism and learning disability (boys 11-19, residential)"),
    "6646004": ("core", "autistic pupils aged 8-19"),
    "6646006": ("core", "autistic pupils aged 11-19 (Autism Initiatives)"),
    "6646009": ("core", "autistic pupils aged 5-16 (day school)"),
    "6656042": ("core", "boys 11-18 with complex behaviour, emotional and social difficulties and autism"),
    "6656047": ("core", "pupils 7-18 with social and emotional needs or autism"),
    "6656046": ("core", "pupils 11-18 with social, emotional and mental health needs, trauma and attachment needs or autism"),
    "6666047": ("core", "autistic pupils aged 8-19 (residential)"),
    "6666052": ("core", "pupils 4-19 with an autism diagnosis"),
    "6696015": ("core", "pupils 5-19 with complex needs, mainly communication difficulties linked to autism"),
    "6706026": ("core", "pupils 8-18 with complex needs including autism and social, emotional and behavioural challenges"),
    "6706028": ("core", "pupils 5-19 with autism"),
    "6716000": ("core", "pupils 8-18 with an autism diagnosis"),
    "6796014": ("core", "pupils 7-18 with autism and social, emotional and mental health needs"),
    "6806009": ("core", "pupils 7-16 with autism and additional learning needs"),
    "6816094": ("core", "pupils 5-19 with autism and social, emotional and mental health needs (operator's description)"),
    "6766092": ("core", "pupils 8-18 with autism, speech and language difficulties and profound and multiple learning difficulties"),
    "6816087": ("broad", "pupils with complex physical needs and associated learning difficulties, including autism"),
    "6816095": ("broad", "pupils 7-19 with moderate or severe learning difficulties, social, emotional and mental health needs or autism"),
    "6816104": ("broad", "pupils 7-18 with specific learning difficulties such as dyslexia, and some with autism or ADD"),
    "6666055": ("broad", "primary pupils with mild or moderate needs such as dyslexia or autism"),
    "6686020": ("broad", "pupils 7-18 with social, emotional and mental health needs and autism"),
    "6766089": ("broad", "secondary pupils with social, emotional and mental health needs or ADHD"),
}
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
    ind_rows = sheet(ET.fromstring(zipfile.ZipFile(path).read("content.xml")), "Independent")
    ind_ix = {h: i for i, h in enumerate(ind_rows[0])}
    ind = [r for r in ind_rows[1:] if r[0].strip() in INDEP]
    if len(ind) != len(INDEP):
        rc.note_failure("wales independent", f"{len(INDEP) - len(ind)} listed school numbers missing from the sheet")
    jobs = [(r, ix, "special") for r in sp] + [(r, {h: i for i, h in enumerate(pru_rows[0])}, "pru") for r in pru] + \
           [(r, ind_ix, "indep") for r in ind]
    look, failed = postcode_lookup([norm_pc(r[i["Postcode"]]) for r, i, _k in jobs if r[i["Postcode"]]])
    out, nogeo = [], 0
    for r, ix, kind in jobs:
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
        dg = re.sub(r"\D", "", ph)
        if kind == "indep" and len(dg) == 10 and dg[0] in "123789":  # leading 0 lost in the sheet
            ph = "0" + dg
            dg = ph
        if ph.upper() == "NULL" or dg.startswith("07"):  # missing, or a mobile number
            ph = ""
        if kind == "indep":
            breadth, who = INDEP[r[0].strip()]
            out.append(rc.entry(smart(r[ix["School Name"]]), INDEP_SOURCE, "education", ["Special education", "Education"],
                                f"Independent school ({r[ix['Local Authority']]}) for {who}. Checked against Estyn inspection reports; Welsh Government school number {r[0]}.",
                                address=addr, phone=ph or None, lat=hit[0], lng=hit[1], external_id=f"wales-school:{r[0]}",
                                breadth=breadth, scope=None if "autis" in who else "general"))
            continue
        if kind == "pru":
            out.append(rc.entry(smart(r[ix["School Name"]]), PRU_SOURCE, "education", ["Pupil referral unit", "Education"],
                                f"Pupil referral unit ({r[ix['Local Authority']]}): local-authority alternative provision for pupils who cannot attend a mainstream school, including some with additional learning needs. Welsh Government school number {r[0]}.",
                                address=addr, phone=ph or None, lat=hit[0], lng=hit[1], external_id=f"wales-school:{r[0]}", breadth="broad", scope="general"))
            continue
        out.append(rc.entry(smart(r[ix["School Name"]]), SOURCE, "education", ["Special education", "Education"],
                            f"Maintained special school ({r[ix['Local Authority']]}), Welsh Government school number {r[0]}.",
                            address=addr, phone=ph or None, lat=hit[0], lng=hit[1], external_id=f"wales-school:{r[0]}", scope="general"))
    print(f"{len(sp)} special schools, {len(pru)} PRUs, {len(ind)} independent; {nogeo} without a geocode")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_wales_schools.json"), out)
    rc.spot_check(fin, 10, fields=("name", "address", "type"))


if __name__ == "__main__":
    main()
