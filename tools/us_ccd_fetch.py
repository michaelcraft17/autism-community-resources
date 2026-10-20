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

Year: the current year back 3 years, newest first. An older year is used only when the newer one is not
published (HTTP 404, or a first page with zero results and no next page). Any other error -- timeout, 5xx
after rc.get's retries, a bad body, a failure on a later page, fewer rows than the API's "count" -- ends the
run non-zero, so a partial year is never used and never cached. The year used is printed and recorded as
rc.STATUS["input"].

Usage:
    python3 tools/us_ccd_fetch.py
Writes:
    tools/us_ccd_scratch/ccd_<year>.json    raw API response, written only once complete (gitignored)
    new_resources_us_ccd.json               resource-schema output (repo root)
"""
import json
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "us_ccd_scratch")
OUT_PATH = os.path.join(rc.REPO, "new_resources_us_ccd.json")
SOURCE = "US NCES Common Core of Data (Urban Institute Education Data API) - public special-education schools"
OPEN_STATUSES = {1, 3, 4, 5, 7}   # open, new, added, changed boundary, reopened


def results(page, url):
    """A page's rows; anything but a dict with a "results" list is a bad body and raises."""
    if not isinstance(page, dict) or not isinstance(page.get("results"), list):
        raise ValueError(f"unexpected CCD API response from {url}: {str(page)[:200]}")
    return page["results"]


def fetch(year):
    """All rows for `year`, or None when that year is not published (HTTP 404 or no results).
    Every other failure raises; the cache is written only after the last page."""
    path = os.path.join(SCRATCH, f"ccd_{year}.json")
    if os.path.exists(path):
        rows = json.load(open(path))
        if rows:   # an empty list cached by an older version means "ask again"
            return rows
    url = f"https://educationdata.urban.org/api/v1/schools/ccd/directory/{year}/?school_type=2"
    try:
        page = rc.get_json(url, timeout=180)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    rows, expected, seen = results(page, url), page.get("count"), {url}
    if not rows:
        if expected or page.get("next"):
            raise ValueError(f"CCD {year}: empty first page but count={expected!r}, next={page.get('next')!r}")
        return None
    while page.get("next"):
        url = page["next"]
        if url in seen:
            raise ValueError(f"CCD {year}: paging loop at {url}")
        seen.add(url)
        page = rc.get_json(url, timeout=180)
        rows += results(page, url)
    if isinstance(expected, int) and len(rows) != expected:
        raise ValueError(f"CCD {year}: got {len(rows)} rows, the API reports count={expected}")
    os.makedirs(SCRATCH, exist_ok=True)
    with open(path + ".part", "w") as f:
        json.dump(rows, f)
    os.replace(path + ".part", path)
    return json.load(open(path))


def main():
    newest = time.localtime().tm_year
    for year in range(newest, newest - 4, -1):
        rows = fetch(year)
        if rows:
            break
        print(f"CCD {year}: not published (HTTP 404 or no results)")
    else:
        sys.exit(f"CCD: none of {newest}..{newest - 3} is published")
    rc.STATUS["input"] = f"CCD {year}"
    print(f"input: CCD {year} ({len(rows)} special-education schools)")
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
