#!/usr/bin/env python3
"""
Scotland -- Care Inspectorate datastore (Open Government Licence): the monthly CSV of every registered care service.
    page: https://www.careinspectorate.scot/resources-data/publications-and-statistics/library  (datastore <date>)
    file: https://ci-web-media-production-bucket.s3.eu-west-2.amazonaws.com/assets/resources/datastore/<yymmdd>datastoreexternal.csv
Usage: python3 tools/scotland_ci_fetch.py [yymmdd]   (default 260831)

Core: Active, publicly listed (PublicList == Yes) services for people with a learning disability or a physical /
sensory impairment: Subtype / AdditionalSubtypes of "Learning Disabilities" or "Physical and Sensory Impairment", a care
home whose main area of care is learning difficulties, autism or physical disability, or "autis*/asperger*" in the name.
Day care of children (nurseries) is dropped unless the name says autism. The CSV is cp1252.
The manager name and e-mail columns are personal data and are never read. Services are premises (care homes, support
offices), so the full postcode is used (postcodes.io, ONS centroids; outward-code centroid when unknown).
Output: new_resources_scotland_ci.json
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402
from oscr_fetch import postcode_lookup, norm_pc, smart  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "scotland_ci_scratch")
SOURCE = "Scotland Care Inspectorate datastore (registered care services)"


def core(r):
    return bool(r["Subtype"] in ("Learning Disabilities", "Physical and Sensory Impairment")
                or re.search(r"Learning Disab|Physical and Sensory", r["AdditionalSubtypes"])
                or r["CareHome_Main_Area_of_Care"] in ("Learning difficulties", "Autism spectrum disorders", "Physical disability or illness")
                or re.search(r"autis|asperger", r["ServiceName"], re.I))


def main():
    ymd = sys.argv[1] if len(sys.argv) > 1 else "260831"
    path = rc.download(f"https://ci-web-media-production-bucket.s3.eu-west-2.amazonaws.com/assets/resources/datastore/{ymd}datastoreexternal.csv",
                       os.path.join(SCRATCH, f"{ymd}datastoreexternal.csv"))
    rc.STATUS["input"] = f"Care Inspectorate datastore {ymd}"
    rows = [r for r in csv.DictReader(open(path, encoding="cp1252", errors="replace"))
            if r["ServiceStatus"] == "Active" and r["PublicList"] == "Yes" and core(r)
            and (r["CareService"] != "Day Care of Children" or re.search(r"autis|asperger", r["ServiceName"], re.I))]
    look, failed = postcode_lookup([norm_pc(r["Service_Postcode"]) for r in rows if rc.clean(r["Service_Postcode"])])
    entries, nogeo = [], 0
    for r in rows:
        pc = norm_pc(r["Service_Postcode"])
        if pc in failed:
            rc.note_failure("postcodes.io", f"{r['CSNumber']}: {failed[pc]}")
            continue
        hit = look.get(pc)
        if not hit or not rc.plausible("GB", *hit):
            nogeo += 1
            continue
        cs, st = r["CareService"], r["Subtype"]
        if cs == "Care Home Service":
            services, typ = ["Residential homes", "Residential & Social Care"], "social"
        elif cs == "Housing Support Service":
            services, typ = ["Supported living", "Residential & Social Care"], "social"
        else:
            services, typ = ["Home-Based Support", "Information & Support"], "general_support"
        if r["CareHome_Main_Area_of_Care"] == "Autism spectrum disorders" or re.search(r"autis|asperger", r["ServiceName"], re.I):
            scope, services = None, services + ["Autism Support"]
        else:
            scope = "general"
        addr = ", ".join(x for x in (smart(rc.clean(r[k])) for k in ("Address_line_1", "Address_line_2", "Address_line_3", "Address_line_4", "Service_town")) if x)
        addr = f"{addr}, {pc}" if addr else pc
        prov = rc.clean(r["ServiceProvider"])
        places = rc.clean(r["Registered_Places"])
        desc = (f"Care Inspectorate registered {cs.lower()} ({r['CSNumber']}) for people with a learning disability or physical / sensory impairment"
                + (f", provided by {prov}" if prov else "") + (f"; {places} registered places" if places.isdigit() and places != "0" else "") + ".")
        entries.append(rc.entry(smart(r["ServiceName"]), SOURCE, typ, services, desc, address=addr,
                                phone=rc.clean(r["Service_Phone_Number"]) or None, lat=hit[0], lng=hit[1],
                                external_id=f"scci:{r['CSNumber']}", scope=scope))
    print(f"{len(rows)} services; {nogeo} without a geocode")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_scotland_ci.json"), entries)
    rc.spot_check(out, 20, fields=("name", "address", "type"))


if __name__ == "__main__":
    main()
