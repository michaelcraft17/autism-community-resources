#!/usr/bin/env python3
"""
US public special-education schools from the NCES Common Core of Data (CCD), served keyless by the
Urban Institute Education Data API:

    https://educationdata.urban.org/api/v1/schools/ccd/directory/<year>/?school_type=2

school_type=2 is NCES's "special education school" type (~1,950 schools, state schools for the deaf and
blind, special-education centres run by districts and cooperatives, ...). Every row carries its own
latitude/longitude, a location address and a phone, so no geocoding is needed. Private special-education
schools are in NCES's PSS frame, which is not covered here (its special-education typology field was
never inspected -- see HANDOFF.md).

Rows are marked disability_scope "general": special-education schools serve every disability category.
Closed (status 2), future (6) and inactive (8) schools are skipped.

Usage:
    python3 tools/us_ccd_fetch.py
Writes:
    tools/us_ccd_scratch/ccd_<year>.json    raw API response (gitignored)
    new_resources_us_ccd.json               resource-schema output (repo root)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "us_ccd_scratch")
OUT_PATH = os.path.join(rc.REPO, "new_resources_us_ccd.json")
SOURCE = "US NCES Common Core of Data (Urban Institute Education Data API) - public special-education schools"
OPEN_STATUSES = {1, 3, 4, 5, 7}   # open, new, added, changed boundary, reopened


def fetch(year):
    path = os.path.join(SCRATCH, f"ccd_{year}.json")
    if not os.path.exists(path):
        os.makedirs(SCRATCH, exist_ok=True)
        rows, url = [], f"https://educationdata.urban.org/api/v1/schools/ccd/directory/{year}/?school_type=2"
        while url:
            page = rc.get_json(url, timeout=180)
            rows += page["results"]
            url = page.get("next")
        json.dump(rows, open(path, "w"))
    return json.load(open(path))


def main():
    rows = []
    for year in (2024, 2023):
        try:
            rows = fetch(year)
        except Exception as e:  # noqa: BLE001
            print(f"{year}: {e}")
        if rows:
            print(f"CCD {year}: {len(rows)} special-education schools")
            break
    entries, skipped = [], 0
    for r in rows:
        if r.get("school_status") not in OPEN_STATUSES:
            skipped += 1
            continue
        lat, lng = r.get("latitude"), r.get("longitude")
        if lat in (None, -1, -2, -3) or not rc.plausible("US", lat, lng):
            skipped += 1
            continue
        city, state, zip_ = rc.clean(r.get("city_location")), rc.clean(r.get("state_location")), rc.clean(r.get("zip_location"))
        street = rc.clean(r.get("street_location"))
        if not (street and city and state):
            skipped += 1
            continue
        addr = f"{street}, {city}, {state} {zip_}".strip()
        phone = rc.clean(r.get("phone"))
        if phone and len(phone) == 13 and phone[0] == "(" and phone[4] == ")":
            phone = f"{phone[:5]} {phone[5:]}"
        lea = rc.clean(r.get("lea_name"))
        entries.append(rc.entry(
            r["school_name"], SOURCE, "education", ["Special Education"],
            f"Public special-education school listed in the US National Center for Education Statistics Common Core of Data"
            + (f" (operated by {lea})." if lea else "."),
            address=addr, phone=phone, lat=lat, lng=lng, external_id=f"nces:{r['ncessch']}", scope="general"))
    print(f"skipped {skipped} (closed/inactive/no usable coordinates or address)")
    out = rc.finalize(OUT_PATH, entries)
    rc.spot_check(out, 8)


if __name__ == "__main__":
    main()
