#!/usr/bin/env python3
"""
Canada -- CRA List of charities 2024 (open.canada.ca, Open Government Licence - Canada).

  ident_2024_updated.csv   BN, Category, Sub Category, Designation, Legal Name, Account Name, address, city, province, postal code
  weburl_2024_updated.csv  BN, #, Contact URL

Selection (core): sub-categories 0010/0012 (schools for students with disabilities), 0110/0014 (services for adults and
children with developmental disabilities), 0140/0005 (therapeutic programs for persons with disabilities), plus legal or
account names that match a disability term (English and French). Charities whose programme text merely mentions autism
(~218) are not merged. Street address, city and province are geocoded with Nominatim (cached): street first, then the
town; PO-Box-only charities are placed by town. Output: new_resources_cra.json
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "cra_scratch")
SOURCE = "Canada Revenue Agency List of charities 2024 (open.canada.ca)"
BASE = "https://open.canada.ca/data/dataset/80c00cdb-1358-415c-bb8b-0de7f12675b8/resource/"
IDENT_URL = BASE + "694fdc72-eae4-4ee0-83eb-832ab7b230e3/download/ident_2024_updated.csv"
WEB_URL = BASE + "e3567bb5-5d98-44d0-b0e8-9cdd3732c9e4/download/weburl_2024_updated.csv"
SUBCATS = {("0010", "0012"): "Schools for students with disabilities", ("0110", "0014"): "Services for adults and children with developmental disabilities",
           ("0140", "0005"): "Therapeutic programs for persons with disabilities"}
NAME_RE = re.compile(
    r"autis|asperger|\bdisab|handicap|special needs|developmental|down syndrome|trisomie|cerebral palsy|paralysie c[ée]r|\bdeaf\b|\bsourd|"
    r"\bblind\b|\baveugle|intellectual|d[ée]ficience|\badhd\b|dyslex|epilep|\bspecial olympics|neurodiver|neurodev|learning (disab|differ)|"
    r"besoins sp[ée]ciaux|\bfasd\b|fetal alcohol|spina bifida|muscular dystrophy|dystrophie", re.I)
PROVINCE = {"AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick", "NL": "Newfoundland and Labrador", "NS": "Nova Scotia",
            "NT": "Northwest Territories", "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec", "SK": "Saskatchewan", "YT": "Yukon"}


def need(path, url):
    if not os.path.exists(path):
        os.makedirs(SCRATCH, exist_ok=True)
        rc.download(url, path)


def smart(s):
    s = rc.clean(s)
    return s.title() if s.isupper() else s


def main():
    csv.field_size_limit(10**8)
    ip, wp = os.path.join(SCRATCH, "ident.csv"), os.path.join(SCRATCH, "web.csv")
    need(ip, IDENT_URL)
    need(wp, WEB_URL)
    web = {}
    for r in csv.DictReader(open(wp, encoding="utf-8")):
        web.setdefault(r["BN/NE"], r["Contact URL"])
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="ca")
    entries, nogeo = [], 0
    for r in csv.DictReader(open(ip, encoding="utf-8")):
        sub = SUBCATS.get((r["Category"], r["Sub Category"]))
        name = r["Account Name"] or r["Legal Name"]
        if not sub and not (NAME_RE.search(r["Legal Name"]) or NAME_RE.search(r["Account Name"])):
            continue
        if not sub and re.search(r"day ?care|child ?care|garderie|preschool|nursery", name, re.I):   # "developmental" daycare centres
            continue
        street = rc.clean(", ".join(x for x in (r["Address Line 1"], r["Address Line 2"]) if rc.clean(x)))
        city, prov, pc = smart(r["City"]), rc.clean(r["Province"]), rc.clean(r["Postal Code"])
        pcs = f"{pc[:3]} {pc[3:]}" if len(pc) == 6 else pc
        po = bool(re.search(r"\bp\.?\s?o\.?\s*box|\bC\.?P\.?\s+\d|\bsuccursale|\bbox\s+\d|\brr\s*\d", street, re.I))
        hit = None
        if street and not po:
            hit = geoc.geocode(f"{street.title()}, {city}, {PROVINCE.get(prov, prov)}, Canada")
        if not hit:
            hit = geoc.geocode(f"{city}, {PROVINCE.get(prov, prov)}, Canada")
        if not hit or not rc.plausible("CA", hit[0], hit[1]):
            nogeo += 1
            continue
        typ = "education" if sub and sub.startswith("Schools") else ("therapy" if sub and sub.startswith("Therapeutic") else
              ("advocacy" if re.search(r"association|society|soci[ée]t[ée]|alliance|federation|f[ée]d[ée]ration|regroupement|council|conseil", name, re.I) else "general_support"))
        services = {"education": ["Education"], "therapy": ["Therapy"], "advocacy": ["Advocacy", "Information & Support"]}.get(typ, ["Information & Support"])
        desc = "Registered charity (CRA)" + (f", category: {sub.lower()}." if sub else " with a disability-related name.")
        addr = ", ".join(x for x in (street.title() if street and not po else "", city, f"{prov} {pcs}".strip(), "Canada") if x)
        url = rc.clean(web.get(r["BN"]))
        if url and not url.lower().startswith("http"):
            url = "http://" + url
        entries.append(rc.entry(smart(name), SOURCE, typ, services, desc, address=addr, website=rc.clean_url(url) if url else None,
                                lat=hit[0], lng=hit[1], external_id=f"ca-bn:{r['BN']}",
                                scope=None if re.search(r"autis", name, re.I) else "general"))
    print(f"{len(entries)} entries; {nogeo} without a geocode")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_cra.json"), entries)
    rc.spot_check(out, 30, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
