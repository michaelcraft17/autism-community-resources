#!/usr/bin/env python3
"""
Australia ACNC register, "People with Disabilities" beneficiary flag (BROAD tier), data.gov.au (CC BY 3.0 AU).
acnc_fetch.py holds the ~1,240 charities with a disability-classified program in the AIS file; this adds the 15k other
charities that merely tick the "People with Disabilities" beneficiary box. 8,600 of those tick every box, so the layer is
kept to charities that tick at most 2 of the 26 beneficiary boxes, or have a disability word in the name.
Located at suburb level only (the register's business address is often a volunteer's home): Nominatim "town, state postcode"
(cache geocode_cache.jsonl, shared with acnc_fetch.py), falling back to the postcode. The street is not published.
Grant-making trusts / ancillary funds and rows without a town or postcode are dropped. Id au-acnc-dis:<ABN>, scope general.
Output: new_resources_acnc_disability.json   Raw: tools/acnc_scratch/main.csv
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402
import acnc_fetch as af  # noqa: E402

BEN = ("Aboriginal_or_TSI", "Adults", "Aged_Persons", "Children", "Communities_Overseas", "Early_Childhood", "Ethnic_Groups",
       "Families", "Females", "Financially_Disadvantaged", "LGBTIQA+", "General_Community_in_Australia", "Males",
       "Migrants_Refugees_or_Asylum_Seekers", "Other_Beneficiaries", "Other_Charities", "People_at_risk_of_homelessness",
       "People_with_Chronic_Illness", "People_with_Disabilities", "Pre_Post_Release_Offenders", "Rural_Regional_Remote_Communities",
       "Unemployed_Person", "Veterans_or_their_families", "Victims_of_crime", "Victims_of_Disasters", "Youth")
NAME = re.compile(r"disab|autis|asperger|special needs|inclusi|wheelchair|blind|vision|deaf|hearing|sensory|ndis|accessib|"
                  r"cerebral|down syndrome|therapy|carers?\b|respite|riding for", re.I)
SOURCE = "Australia ACNC charity register, People with Disabilities beneficiary flag (data.gov.au)"
MAX_BOXES = 2
OFFTOPIC = re.compile(r"church|parish|ministr|mosque|temple|rsl\b|men'?s shed|lions club|rotary|sub-branch|roadshow|emergency services|aged care|vietnamese|\bsociety\b.*memorial", re.I)


def main():
    csv.field_size_limit(10 ** 8)
    mp = os.path.join(af.SCRATCH, "main.csv")
    af.need(mp, af.MAIN_URL)
    reg = list(csv.DictReader(open(mp, encoding="utf-8-sig")))
    if len(reg) < 50000 or any(b not in reg[0] for b in BEN):
        raise RuntimeError(f"ACNC main register: {len(reg)} rows or a beneficiary column missing -- layout changed?")
    rc.STATUS["input"] = f"ACNC main register {len(reg)} rows"
    geoc = rc.Geocoder(os.path.join(af.SCRATCH, "geocode_cache.jsonl"), countrycodes="au")
    entries, skip = [], {"flag": 0, "noisy": 0, "trust/no town": 0, "no geocode": 0}
    for m in reg:
        if m["People_with_Disabilities"] != "Y":
            continue
        skip["flag"] += 1
        name = rc.clean(m["Charity_Legal_Name"])
        if OFFTOPIC.search(name) and not NAME.search(name):
            skip["noisy"] += 1
            continue
        if sum(m[b] == "Y" for b in BEN) > MAX_BOXES and not NAME.search(name):
            skip["noisy"] += 1
            continue
        town, state, pc = rc.clean(m["Town_City"]), rc.clean(m["State"]), rc.clean(m["Postcode"])
        if re.search(r"^the trustees? (for|of)\b|ancillary fund|\bpaf\b|\bfoundation trust\b", name, re.I) or not (town and pc):
            skip["trust/no town"] += 1
            continue
        hit = geoc.geocode(f"{town}, {af.STATE_NAME.get(state, state)} {pc}, Australia")
        if not hit and not geoc.last_failed:
            hit = geoc.geocode(f"{pc}, Australia")
        if not hit or not rc.plausible("AU", *hit):
            skip["no geocode"] += 1
            continue
        abn = m["ABN"]
        entries.append(rc.entry(name.title() if name.isupper() else name, SOURCE, "general_support", ["Information & Support"],
                                f"Registered charity (ACNC) that lists people with disabilities among its beneficiaries. Shown at suburb level.",
                                address=f"{town} {state} {pc}, Australia", website=rc.clean_url(m["Charity_Website"]),
                                lat=hit[0], lng=hit[1], external_id=f"au-acnc-dis:{abn}", breadth="broad", scope="general"))
    print(f"{skip}")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_acnc_disability.json"), entries)
    rc.spot_check(out, 20, fields=("name", "address"))


if __name__ == "__main__":
    main()
