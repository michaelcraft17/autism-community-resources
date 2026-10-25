#!/usr/bin/env python3
"""
Wales -- Care Inspectorate Wales (CIW) full services export (open, keyless CSV, regenerated nightly):
    https://digital.careinspectorate.wales/api/DataExport
Usage: python3 tools/ciw_fetch.py [--children-homes]

Core: adult care homes / special-school residential units / adult placement (Shared Lives) schemes whose "Care and
support for" tag says learning disability, physical disability or neurodiverse needs, plus domiciliary services with
autism / learning disability in the name. Children's homes (263) are left out unless --children-homes is given (owner
chose to include them at town level, 2026-10-25); CIW gives them no postcode, so they are placed by town + local authority
(Nominatim) and shown as town, local authority. Dementia-only, mental-health-only, childcare and child
minders are never included.
The Responsible Individual / Registered Person columns (and the Standard conditions text, which repeats the name) are
personal data and never read. E-mail addresses and mobile numbers are not kept; homes are small residences, so the pin is
the outward-code centroid (postcodes.io) and the address is town + outward code, never the street.
Output: new_resources_ciw.json
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402
from oscr_fetch import outcode_lookup, LookupFailed, smart  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "ciw_scratch")
URL = "https://digital.careinspectorate.wales/api/DataExport"
SOURCE = "Wales Care Inspectorate Wales (CIW) registered services"
TAG = re.compile(r"learning disab|physical disab|neurodiver", re.I)
NAME = re.compile(r"autis|asperger|learning disab", re.I)
TYPES = ("Care Home Service", "Special School Residential Service", "Adult Placement Service", "Domiciliary Support Service")


_G = []


def geoc():
    if not _G:
        _G.append(rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="gb"))
    return _G[0]


def main():
    children = "--children-homes" in sys.argv
    path = rc.download(URL, os.path.join(SCRATCH, "ciw.csv")) if not os.path.exists(os.path.join(SCRATCH, "ciw.csv")) else os.path.join(SCRATCH, "ciw.csv")
    rc.STATUS["input"] = "CIW DataExport"
    csv.field_size_limit(10**8)
    entries, nogeo, nch = [], 0, 0
    for r in csv.DictReader(open(path, encoding="utf-8-sig", errors="replace")):
        t, sub, tag, name = r["Service type"], r["Service sub-type"], r["Care and support for"], rc.clean(r["Service name"])
        if t not in TYPES:
            continue
        if t == "Domiciliary Support Service":
            ok = bool(NAME.search(name))
        else:
            ok = bool(TAG.search(tag) or NAME.search(name))
        if not ok:
            continue
        if sub == "Childrens Home" and not children:
            nch += 1
            continue
        pc = re.sub(r"\s+", "", rc.clean(r["Service postcode"]).upper())
        oc = pc[:-3] if len(pc) > 4 else pc
        if not oc:   # CIW publishes no postcode for children's homes: town + local authority, Nominatim
            tw, la = rc.clean(r["Service town/city"]), rc.clean(r["Local authority"])
            hit = geoc().geocode(f"{tw}, {la}, Wales, United Kingdom") if tw else None
            hit = hit or (geoc().geocode(f"{la}, Wales, United Kingdom") if la else None)
        else:
            try:
                hit = outcode_lookup(oc)
            except LookupFailed as e:
                rc.note_failure("postcodes.io", f"{r['Service URN']}: {e}")
                continue
        if not hit or not rc.plausible("GB", *hit):
            nogeo += 1
            continue
        town = smart(rc.clean(r["Service town/city"]))
        address = ", ".join(x for x in (town, oc or rc.clean(r["Local authority"])) if x)
        if t == "Care Home Service":
            services, typ = ["Residential homes", "Residential & Social Care"], "social"
        elif t == "Special School Residential Service":
            services, typ = ["Residential homes", "Education"], "social"
        elif t == "Adult Placement Service":
            services, typ = ["Shared Lives", "Residential & Social Care"], "social"
        else:
            services, typ = ["Home-Based Support", "Information & Support"], "general_support"
        autism = bool(re.search(r"neurodiver|autis|asperger", tag + " " + name, re.I))
        if autism:
            services = services + ["Autism Support"]
        prov = rc.clean(r["Provider name"])
        places = rc.clean(r["Maximum no. of places"])
        who = "autistic / neurodiverse people" if autism else "people with a learning or physical disability"
        desc = (f"CIW registered {t.lower()} ({r['Service URN']}) for {who}" + (f", provided by {prov}" if prov else "")
                + (f"; {places} places" if places.isdigit() and places != "0" else "") + ".")
        phone = rc.clean(r["Primary telephone number"])
        site = rc.clean(r["Website"])
        if site and not site.lower().startswith("http"):
            site = "http://" + site
        entries.append(rc.entry(name, SOURCE, typ, services, desc, address=address, phone=None if phone.startswith("07") else phone or None,
                                website=rc.clean_url(site) if site else None, lat=hit[0], lng=hit[1],
                                external_id=f"ciw:{r['Service URN']}", scope=None if autism else "general"))
    print(f"{len(entries)} entries; {nch} children's homes left out; {nogeo} without a geocode")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_ciw.json"), entries)
    rc.spot_check(out, 20, fields=("name", "address", "type"))


if __name__ == "__main__":
    main()
