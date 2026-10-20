#!/usr/bin/env python3
"""
Australia -- ACNC charity register + Annual Information Statement (AIS 2024) programs file, data.gov.au (CC BY 3.0 AU).

  main register  .../datadotgov_main.csv            66k charities with business address, website, beneficiary flags
  AIS programs   .../datadotgov_ais24_programs.csv  one row per program with a Classification

Selection (core): registered charities with at least one program classified Autism spectrum disorder, Disability
services, Family disability resources, Special needs education, Disabled persons' rights, Learning disorders, Down
syndrome or Disability sports. Charities whose only disability program is "Housing for people with disabilities" are not
merged (a charity's business address is sometimes a person's home; see HANDOFF). The 16k charities that merely tick the
"People with Disabilities" beneficiary box are the large noisy set and are not merged.
Program operating locations in the file are region-level ("Western Australia"), so the register's business address is
geocoded instead (Nominatim, cached; street, then suburb + postcode, then postcode). A row whose address text is unchanged
keeps the coordinates the dataset already holds (rc.prior_coords), so a refresh only geocodes new or changed addresses.
Grant-making trusts and rows without an address are dropped before any lookup.

Output: new_resources_acnc.json
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "acnc_scratch")
SOURCE = "Australia ACNC charity register and Annual Information Statement programs (data.gov.au)"
MAIN_URL = "https://data.gov.au/data/dataset/b050b242-4487-4306-abf5-07ca073e5594/resource/8fb32972-24e9-4c95-885e-7140be51be8a/download/datadotgov_main.csv"
AIS_URL = "https://data.gov.au/data/dataset/276ec1bc-4971-461c-88bc-be9f3c99a0f8/resource/09f5fc83-8648-413e-ba5b-793a9d6b305f/download/datadotgov_ais24_programs.csv"
# classification -> (priority, type, service)
CLASSES = {
    "Autism spectrum disorder": (0, "general_support", "Information & Support"),
    "Special needs education": (1, "education", "Education"),
    "Learning disorders": (2, "education", "Education"),
    "Disability services": (3, "general_support", "Information & Support"),
    "Family disability resources": (4, "general_support", "Information & Support"),
    "Down syndrome": (5, "general_support", "Information & Support"),
    "Disabled persons' rights": (6, "advocacy", "Advocacy"),
    "Disability sports": (7, "social", "Recreation"),
}
STATE_NAME = {"NSW": "New South Wales", "VIC": "Victoria", "QLD": "Queensland", "WA": "Western Australia", "SA": "South Australia",
              "TAS": "Tasmania", "ACT": "Australian Capital Territory", "NT": "Northern Territory"}


def need(path, url):
    if not os.path.exists(path):
        os.makedirs(SCRATCH, exist_ok=True)
        rc.download(url, path)


def main():
    csv.field_size_limit(10**8)
    mp, ap = os.path.join(SCRATCH, "main.csv"), os.path.join(SCRATCH, "ais24_programs.csv")
    need(mp, MAIN_URL)
    need(ap, AIS_URL)
    main_reg = {r["ABN"]: r for r in csv.DictReader(open(mp, encoding="utf-8-sig"))}
    progs = {}
    housing_only = set()
    for r in csv.DictReader(open(ap, encoding="utf-8-sig")):
        if r["Registration Status"] != "Registered":
            continue
        cl = r["Classification"]
        if cl in CLASSES:
            progs.setdefault(r["ABN"], []).append((cl, rc.clean(r["Program name"])))
        elif cl == "Housing for people with disabilities":
            housing_only.add(r["ABN"])
    housing_only -= set(progs)
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="au")
    entries, nomain, nogeo, skipped = [], 0, 0, 0
    for abn, plist in progs.items():
        m = main_reg.get(abn)
        if not m:
            nomain += 1
            continue
        town, state, pc = rc.clean(m["Town_City"]), rc.clean(m["State"]), rc.clean(m["Postcode"])
        lines = [rc.clean(m[k]) for k in ("Address_Line_1", "Address_Line_2", "Address_Line_3") if rc.clean(m[k])]
        street = ", ".join(lines)
        po = bool(re.search(r"\bp\.?\s?o\.?\s*box|locked bag|GPO box", street, re.I))
        name = rc.clean(m["Charity_Legal_Name"])
        # grant-making trusts / private ancillary funds are not services; entries with no address would sit on the country centroid
        if re.search(r"^the trustees? (for|of)\b|ancillary fund|\bpaf\b", name, re.I) or not (street or town):
            skipped += 1
            continue
        addr = ", ".join(x for x in (street if not po else "", f"{town} {state} {pc}".strip(), "Australia") if x)
        eid = f"au-abn:{abn}"
        # coordinates already in the dataset for this unchanged address, else Nominatim (the address text does not
        # depend on which lookup hits)
        hit = rc.prior_coords(eid, addr)
        if not hit and street and not po:
            hit = geoc.geocode(f"{street}, {town}, {STATE_NAME.get(state, state)} {pc}, Australia")
        if not hit:
            hit = geoc.geocode(f"{town}, {STATE_NAME.get(state, state)} {pc}, Australia") or geoc.geocode(f"{pc}, Australia")
        if not hit or not rc.plausible("AU", hit[0], hit[1]):
            nogeo += 1
            continue
        best = min(plist, key=lambda p: CLASSES[p[0]][0])[0]
        typ = CLASSES[best][1]
        services = []
        for cl, _ in sorted(plist, key=lambda p: CLASSES[p[0]][0]):
            if CLASSES[cl][2] not in services:
                services.append(CLASSES[cl][2])
        names = []
        for _, pn in plist:
            if pn and pn.lower() not in [n.lower() for n in names]:
                names.append(pn)
        desc = f"Registered charity (ACNC) running disability programs: {'; '.join(names[:5])}{'...' if len(names) > 5 else ''}."
        scope = None if (best == "Autism spectrum disorder" or re.search(r"autis|asperger", name, re.I)) else "general"
        entries.append(rc.entry(name.title() if name.isupper() else name, SOURCE, typ, services, desc, address=addr,
                                website=rc.clean_url(m["Charity_Website"]), lat=hit[0], lng=hit[1], external_id=eid,
                                scope=scope))
    print(f"{len(progs)} charities with disability programs; {nomain} not in main register, {nogeo} without a geocode; "
          f"{len(housing_only)} housing-only charities not merged; {skipped} grant-making trusts / no-address rows dropped")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_acnc.json"), entries)
    rc.spot_check(out, 30, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
