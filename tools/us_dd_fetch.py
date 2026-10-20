#!/usr/bin/env python3
"""
US -- state developmental-disability provider registers with coordinates (no geocoding needed).

1. New York OPWDD provider agencies   https://data.ny.gov/resource/ieqx-cqyk.json   (Socrata, keyless, 455 rows,
   Y/N flag per service, location_1 lat/lon). One entry per row, in :id order ($order=:id keeps the order, and which
   duplicate rc.finalize keeps, stable between runs). The run fails if a column the entries are built from is absent
   from every row (Socrata leaves null cells out, so a missing column means it was renamed), if the answer reaches
   $limit, or if no row has usable coordinates.
2. Ohio DODD certified providers      https://maps.ohio.gov/arcgis/rest/services/Hosted/AllProviderDataProd23_view/FeatureServer/0
   (keyless ArcGIS feature service; 83,744 provider x service x site rows, max 1,000 per page). Only sitedescription =
   'Agency' is used: 'Independent' providers are individual people and are not published. One entry per site
   (sitekey), the certified services listed in the description. Site contact names / e-mail addresses are never read.
   The expected row count is asked first (returnCountOnly); the run fails on an ArcGIS "error" body (often sent with
   HTTP 200) or when the pages do not add up to that count, and only a complete list is cached in dd_scratch/.

Both are general (not autism-specific) disability layers: disability_scope "general".
Output: new_resources_ny_opwdd.json, new_resources_ohio_dodd.json -- both written only after both sources were fetched
"""
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "dd_scratch")
NY_SOURCE = "New York OPWDD provider agencies (data.ny.gov)"
OH_SOURCE = "Ohio Department of Developmental Disabilities certified providers (DODD)"
NY_LIMIT = 5000
NY_URL = f"https://data.ny.gov/resource/ieqx-cqyk.json?$limit={NY_LIMIT}&$order=:id"
OH_URL = "https://maps.ohio.gov/arcgis/rest/services/Hosted/AllProviderDataProd23_view/FeatureServer/0/query"
OH_FIELDS = ("objectid,sitekey,providername,agencylocationname,sitedescription,servicename,addressline1,addressline2,city,state,zipcode,"
             "county,latitude,longitude,sitephonenumber,siteurladdress,agesserved")

NY_SERVICES = {
    "intermediate_care_facilities_icf_s": ("Intermediate care facility", "Residential & Social Care"),
    "individual_residential_alternative_ira": ("Residential (IRA)", "Residential & Social Care"),
    "family_care": ("Family care", "Residential & Social Care"),
    "self_direction_services": ("Self-direction", "Information & Support"),
    "individual_support_services_iss": ("Individual support services", "Residential & Social Care"),
    "day_habilitation": ("Day habilitation", "Day Programs"),
    "prevocational": ("Prevocational", "Employment"),
    "supported_employment_enrollments": ("Supported employment", "Employment"),
    "community_habilitation": ("Community habilitation", "Day Programs"),
    "family_support_services": ("Family support services", "Respite Care"),
    "developmental_centers_and_special_population_services": ("Developmental center / special population services", "Residential & Social Care"),
}
# columns every NY entry is built from ("state" has a default and is not required)
NY_COLUMNS = ("service_provider", "street_address", "city", "zip_code", "phone", "url", "location_1",
              "developmental_disability_services_office") + tuple(NY_SERVICES)


def title(s):
    return re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), rc.clean(s).title())


def phone10(s):
    d = re.sub(r"\D", "", str(s or ""))
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else None


def ny():
    rows = rc.get_json(NY_URL)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"NY OPWDD: expected a non-empty JSON list, got {str(rows)[:200]}")
    if len(rows) >= NY_LIMIT:
        raise RuntimeError(f"NY OPWDD: {len(rows)} rows reached $limit={NY_LIMIT}; raise the limit")
    present = set().union(*(r.keys() for r in rows))   # a null cell is left out of its row, so check the whole answer
    missing = [c for c in NY_COLUMNS if c not in present]
    if missing:
        raise RuntimeError(f"NY OPWDD: column(s) {missing} absent from all {len(rows)} rows -- renamed upstream?")
    out, nocoords = [], 0
    for r in rows:
        loc = r.get("location_1") or {}
        try:
            lat, lng = float(loc["latitude"]), float(loc["longitude"])
        except Exception:  # noqa: BLE001
            nocoords += 1
            continue
        if not rc.plausible("US", lat, lng):
            continue
        flags = [NY_SERVICES[k] for k in NY_SERVICES if r.get(k) == "Y"]
        services = []
        for _, s in flags:
            if s not in services:
                services.append(s)
        services = services or ["Information & Support"]
        name = rc.clean(r["service_provider"])
        name = re.sub(r"^\d{3,4} - ", "", name)
        addr = ", ".join(x for x in (title(r.get("street_address")), title(r.get("city")), f"{r.get('state', 'NY')} {rc.clean(r.get('zip_code'))}") if x.strip())
        desc = ("Agency certified by the NY Office for People With Developmental Disabilities (OPWDD)"
                + (": " + ", ".join(n for n, _ in flags).lower() + "." if flags else ".")
                + f" Region: {rc.clean(r.get('developmental_disability_services_office')).title()}.")
        web = (r.get("url") or {}).get("url") if isinstance(r.get("url"), dict) else None
        out.append(rc.entry(name.title() if name.isupper() else name, NY_SOURCE, "social", services, desc, address=addr,
                            phone=phone10(r.get("phone")) or rc.clean(r.get("phone")) or None, website=rc.clean_url(web), lat=lat, lng=lng,
                            external_id=f"ny-opwdd:{rc.clean(r['service_provider'])}:{rc.clean(r.get('street_address'))}:{rc.clean(r.get('zip_code'))}",
                            scope="general"))
    print(f"NY OPWDD: {len(rows)} rows, {nocoords} without location_1 coordinates")
    if nocoords == len(rows):
        raise RuntimeError("NY OPWDD: no row has location_1 latitude/longitude -- column format changed?")
    return out


def oh_query(params):
    """One ArcGIS query. ArcGIS often reports an error as HTTP 200 with an "error" object, so that raises too."""
    q = urllib.parse.urlencode(params)
    d = json.loads(rc.get(OH_URL + "?" + q, delay=0.3, timeout=120))
    if not isinstance(d, dict) or "error" in d:
        raise RuntimeError(f"Ohio DODD ArcGIS error for {q}: {str(d)[:300]}")
    return d


def oh_rows():
    path = os.path.join(SCRATCH, "ohio_rows.json")
    if os.path.exists(path):
        return json.load(open(path))
    where = "sitedescription='Agency'"
    expected = oh_query({"where": where, "returnCountOnly": "true", "f": "json"}).get("count")
    if not isinstance(expected, int) or expected <= 0:
        raise RuntimeError(f"Ohio DODD: bad returnCountOnly answer: count={expected!r}")
    rows, off = [], 0
    while True:
        d = oh_query({"where": where, "outFields": OH_FIELDS, "resultOffset": off, "resultRecordCount": 1000,
                      "orderByFields": "objectid", "f": "json"})
        f = d.get("features")
        if not isinstance(f, list):
            raise RuntimeError(f"Ohio DODD: no features list at offset {off}: {str(d)[:300]}")
        if not f:
            break
        rows += [x["attributes"] for x in f]
        off += len(f)
        if len(rows) > expected:   # data changed mid-run, or the offset was ignored
            raise RuntimeError(f"Ohio DODD: {len(rows)} rows paged, more than the {expected} counted")
    if len(rows) != expected:
        raise RuntimeError(f"Ohio DODD: {len(rows)} rows paged, {expected} counted -- incomplete, not cached")
    ids = [r.get("objectid") for r in rows]
    if None not in ids and len(set(ids)) != len(ids):
        raise RuntimeError("Ohio DODD: pages overlap (repeated objectid) -- not cached")
    os.makedirs(SCRATCH, exist_ok=True)
    with open(path + ".part", "w") as fh:
        json.dump(rows, fh)
    os.replace(path + ".part", path)
    return rows


def ohio():
    sites = {}
    for r in oh_rows():
        if r.get("sitedescription") != "Agency":
            continue
        s = sites.setdefault(r["sitekey"], {"r": r, "svc": []})
        sv = rc.clean(r.get("servicename"))
        if sv and sv not in s["svc"]:
            s["svc"].append(sv)
    out = []
    for key, s in sites.items():
        r = s["r"]
        lat, lng = r.get("latitude"), r.get("longitude")
        if lat is None or lng is None or not rc.plausible("US", lat, lng):
            continue
        a1 = rc.clean(r.get("addressline1"))
        if not a1:
            continue
        addr = ", ".join(x for x in (title(a1), title(r.get("city")), f"{rc.clean(r.get('state')) or 'OH'} {rc.clean(r.get('zipcode'))}") if x.strip())
        name = rc.clean(r.get("providername"))
        svc = s["svc"]
        has = lambda *w: any(re.search(p, x, re.I) for x in svc for p in w)  # noqa: E731
        services = []
        for cond, label in ((has("shared living", "supported living", "residential", "intermediate care"), "Residential & Social Care"),
                            (has("respite"), "Respite Care"), (has("day support", "habilitation"), "Day Programs"),
                            (has("employment", "career"), "Employment"), (has("personal care", "nursing", "behavio", "clinical", "social work"), "Home & Personal Care")):
            if cond:
                services.append(label)
        services = services or ["Information & Support"]
        desc = f"Agency certified by the Ohio Department of Developmental Disabilities (DODD): {', '.join(svc[:10]).lower()}{'...' if len(svc) > 10 else ''}."
        web = rc.clean(r.get("siteurladdress"))
        if web and not web.startswith("http"):
            web = "http://" + web
        out.append(rc.entry(name.title() if name.isupper() else name, OH_SOURCE, "social", services, desc, address=addr,
                            phone=phone10(r.get("sitephonenumber")), website=rc.clean_url(web) if web else None, lat=lat, lng=lng,
                            external_id=f"oh-dodd:{key}", scope="general"))
    return out


def main():
    ny_entries, oh_entries = ny(), ohio()   # both fetched before either file is written: a failure writes neither
    a = rc.finalize(os.path.join(rc.REPO, "new_resources_ny_opwdd.json"), ny_entries)
    b = rc.finalize(os.path.join(rc.REPO, "new_resources_ohio_dodd.json"), oh_entries)
    rc.spot_check(a, 10, fields=("name", "address", "description"))
    rc.spot_check(b, 20, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
