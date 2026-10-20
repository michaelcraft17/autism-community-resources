#!/usr/bin/env python3
"""
New Zealand -- Charities Services register, OData v2 (keyless, plain HTTP): http://www.odata.charities.govt.nz/Organisations

Selection: RegistrationStatus 'Registered' and MainSectorId eq 5 ("People with disabilities"), plus any registered charity
whose name matches an autism / neurodevelopmental term. Officers are never read. Street address, suburb, city and
postcode are geocoded with Nominatim (cached): street first, then suburb/city; PO-Box-only charities are placed by city.
Rows the name / purpose / address filters drop are dropped before any lookup, and a row whose address text is unchanged
keeps the coordinates the dataset already holds (rc.prior_coords), so a refresh only geocodes new or changed addresses.
Output: new_resources_nz_charities.json
"""
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "nz_scratch")
BASE = "http://www.odata.charities.govt.nz/Organisations"
SOURCE = "New Zealand Charities Services register (OData) - official charity register"
SELECT = ("OrganisationId,Name,CharityRegistrationNumber,WebSiteURL,Telephone1,StreetAddressLine1,StreetAddressLine2,StreetAddressSuburb,"
          "StreetAddressCity,StreetAddressPostcode,PostalAddressCity,CharitablePurpose,MainSectorId")
DIS_RE = re.compile(r"disab|autis|asperger|adhd|dyslex|down syndrome|intellectual|handicap|special needs|\bdeaf|blind|cerebral|palsy|epilep|"
                    r"multiple sclerosis|muscular dystrophy|spina bifida|paraplegi|wheelchair|special olympics|neurodiver|hearing (loss|impair)|vision (loss|impair)", re.I)
DIS_NAME_RE = re.compile(r"hearing|vision|sight|neuro|syndrome|mobility|\brett\b|muscular|spinal|brain|\bsense\b|\bcp\b|\bms\b|\bihc\b", re.I)
NAME_FILTER = " or ".join(f"substringof('{t}',tolower(Name))" for t in ("autis", "asperger", "adhd", "dyslex", "down syndrome", "neurodiver", "intellectual disab"))


def fetch(flt, tag):
    path = os.path.join(SCRATCH, f"{tag}.json")
    if os.path.exists(path):
        return json.load(open(path))
    rows, skip = [], 0
    while True:
        q = urllib.parse.urlencode({"$filter": flt, "$select": SELECT, "$top": 200, "$skip": skip, "$format": "json", "$orderby": "OrganisationId"},
                                   quote_via=urllib.parse.quote)
        d = json.loads(rc.get(BASE + "?" + q, delay=0.5, timeout=120))["d"]
        res = d["results"] if isinstance(d, dict) else d
        if not res:
            break
        rows += res
        skip += len(res)
    os.makedirs(SCRATCH, exist_ok=True)
    json.dump(rows, open(path, "w"))
    return rows


def main():
    rows = {}
    for tag, flt in (("sector5", "RegistrationStatus eq 'Registered' and MainSectorId eq 5"),
                     ("names", f"RegistrationStatus eq 'Registered' and ({NAME_FILTER})")):
        for r in fetch(flt, tag):
            rows[r["OrganisationId"]] = r
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="nz")
    entries, nogeo, skipped = [], 0, 0
    for r in rows.values():
        st, sub, city, pc = (rc.clean(r.get(k)) for k in ("StreetAddressLine1", "StreetAddressSuburb", "StreetAddressCity", "StreetAddressPostcode"))
        st2 = rc.clean(r.get("StreetAddressLine2"))
        city = city or rc.clean(r.get("PostalAddressCity"))
        po = bool(re.search(r"\bp\.?\s?o\.?\s*box|private bag|locked bag", st, re.I))
        name = rc.clean(r["Name"])
        purpose = rc.clean(r.get("CharitablePurpose"))
        # sector 5 also holds older-people groups and estates that only make grants through a trustee company (c/o address)
        if (not (DIS_RE.search(name + " " + purpose) or DIS_NAME_RE.search(name)) or re.search(r"older people|elderly|\bseniors?\b|age (concern|connect)", name + " " + purpose[:120], re.I)
                or re.match(r"\s*c/o\b", st, re.I) or re.search(r"perpetual guardian|public trust|trustee", st + " " + st2, re.I)):
            skipped += 1
            continue
        addr = ", ".join(x for x in ((st if not po else ""), (st2 if not po else ""), sub, city, pc, "New Zealand") if x)
        eid = f"nz-cc:{r.get('CharityRegistrationNumber')}"
        # coordinates already in the dataset for this unchanged address, else Nominatim (the address text does not
        # depend on which lookup hits)
        hit = rc.prior_coords(eid, addr)
        if not hit and st and not po:
            hit = geoc.geocode(", ".join(x for x in (st, sub, city, pc, "New Zealand") if x))
        if not hit:
            hit = geoc.geocode(", ".join(x for x in (sub, city, "New Zealand") if x)) or geoc.geocode(f"{city}, New Zealand")
        if not hit or not rc.plausible("NZ", hit[0], hit[1]):
            nogeo += 1
            continue
        typ = "advocacy" if re.search(r"advoca|alliance|federation|league|council|association|society", name, re.I) and not re.search(r"residential|housing|homes?\b", purpose, re.I) else "general_support"
        services = ["Advocacy", "Information & Support"] if typ == "advocacy" else ["Information & Support"]
        desc = f"Registered charity (Charities Services {r.get('CharityRegistrationNumber')})." + (f" Purpose: {purpose[:300]}" if purpose else "")
        entries.append(rc.entry(name.title() if name.isupper() else name, SOURCE, typ, services, desc, address=addr, phone=rc.clean(r.get("Telephone1")) or None,
                                website=rc.clean_url(r.get("WebSiteURL")), lat=hit[0], lng=hit[1], external_id=eid,
                                scope=None if re.search(r"autis|asperger", name, re.I) else "general"))
    print(f"{len(rows)} charities; {nogeo} without a geocode; {skipped} dropped (no disability wording, older-people groups, trustee-company estates)")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_nz_charities.json"), entries)
    rc.spot_check(out, 30, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
