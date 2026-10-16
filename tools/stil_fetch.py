#!/usr/bin/env python3
"""
Denmark: special schools and special-needs education providers from the Danish Ministry of Children and
Education's Institutionsregisteret (STIL), keyless JSON, coordinates included:

    https://institutionsregisteret.stil.dk/frontend-api/Institutions      (all ~9,800 institutions)
    https://institutionsregisteret.stil.dk/frontend-api/InstitutionTypes/GetAll

Core institution types (all disability_scope "general"; Danish special education serves every need):
  1015 Specialskoler for born            1051 Specialskoler for voksne
  1026 Uddannelsesinstitutioner for unge med serlige behov
  1010 Efterskoler med samlet sarligt tilbud
  3001 Behandlings- og specialundervisningstilbud      3002 Specialundervisning pa borne- og ungehjem
  2021 Centre for padagogisk og psykologisk radgivning (PPR)
Only active institutions/units (activeCode 0, 1, 2, 4 = counted/not counted/legal/other active) are kept.
`principalName` is never read (personal data); rows without coordinates are dropped.

Writes tools/stil_scratch/institutions.json (raw, gitignored) and new_resources_stil.json.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "stil_scratch")
SOURCE = "Denmark STIL Institutionsregisteret (Ministry of Children and Education) - official institution register"
BASE = "https://institutionsregisteret.stil.dk/frontend-api/"
CORE = {1015: ("education", ["Special Education"]), 1051: ("education", ["Special Education"]),
        1026: ("education", ["Special Education"]), 1010: ("education", ["Special Education"]),
        3001: ("education", ["Special Education", "Treatment & Support"]),
        3002: ("education", ["Special Education", "Residential & Social Care"]),
        2021: ("general_support", ["Information & Support", "Psychological Counselling"])}
ACTIVE = {0, 1, 2, 4}


def main():
    path = rc.download(BASE + "Institutions", os.path.join(SCRATCH, "institutions.json"))
    rows = json.load(open(path))
    entries, nocoord = [], 0
    for r in rows:
        if r["institutionTypeId"] not in CORE or r["activeCode"] not in ACTIVE:
            continue
        lat, lng = r.get("latitude"), r.get("longitude")
        if not rc.plausible("DK", lat, lng):
            nocoord += 1
            continue
        typ, services = CORE[r["institutionTypeId"]]
        addr = ", ".join(x for x in (rc.clean(r["address"]), f"{r['postalCode']} {rc.clean(r['postalDistrict'])}".strip()) if x)
        muni = rc.clean(r.get("locationMunicipality"))
        desc = f"{rc.clean(r['institutionType'])}" + (f", {rc.clean(r['ownerCodeName']).lower()} institution" if r.get("ownerCodeName") else "") \
            + (f" in {muni}." if muni else ".")
        name = rc.clean(r["institutionName"])
        if r["institutionTypeId"] == 2021 and muni and muni.split()[0].lower() not in name.lower():
            name = f"{name} ({muni})"   # many PPR offices are just called "PPR"
        entries.append(rc.entry(name, SOURCE, typ, services, desc, address=addr,
                                phone=r.get("phoneNumber"), website=rc.clean_url(r.get("website")), lat=lat, lng=lng,
                                external_id=f"stil:{r['institutionNumber']}", scope="general"))
    print(f"STIL: {len(entries)} kept, {nocoord} without usable coordinates")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_stil.json"), entries)
    rc.spot_check(out, 10, fields=("name", "address", "website"))


if __name__ == "__main__":
    main()
