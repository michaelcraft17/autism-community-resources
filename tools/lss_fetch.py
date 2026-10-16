#!/usr/bin/env python3
"""
Sweden -- Socialstyrelsen LSS unit survey 2025 (Enhetsundersökning om LSS), open xlsx.

File: https://www.socialstyrelsen.se/contentassets/778e6eacbcea42139d3851ebc1af4815/2025-10-9811-resultat.xlsx
Sheets "Bostad med särskild serv, enhet" (3,728 housing units: gruppbostad / servicebostad) and
"Daglig verksamhet, enhet " (2,120 day-activity units); header on row 4. No street address or coordinates.
(The sibling file "inloggningsuppgifter-indikator.xlsx" holds respondent login credentials and is never read.)

Privacy (build rules): housing units are people's homes and unit names are often street addresses, so nothing is
pinned and no unit name is published. One entry per (municipality, operator) per sheet, placed at the municipality
centre (Nominatim, cached), with the number of units. Day-activity units are named workplaces; their names are listed
in the description of the municipality/operator entry. Private operators are named only when the name carries a
company/association form (AB, förening, stiftelse ...); otherwise "private provider".

Output: new_resources_sweden_lss.json
"""
import os
import re
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "lss_scratch")
XLSX = os.path.join(SCRATCH, "lss.xlsx")
URL = "https://www.socialstyrelsen.se/contentassets/778e6eacbcea42139d3851ebc1af4815/2025-10-9811-resultat.xlsx"
SOURCE = "Sweden Socialstyrelsen LSS unit survey 2025 (Enhetsundersokning om LSS)"
ORG_FORM = re.compile(r"\b(AB|HB|KB|Ek\.? ?för\.?|ekonomisk förening|förening|stiftelse|kooperativ|ideell|aktiebolag|Stiftelsen|Föreningen|Coop)\b", re.I)


def rows(wb, sheet):
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    for _ in range(4):
        next(it)
    for r in it:
        if r[0] and r[3]:
            yield r


def slug(s):
    return re.sub(r"[^0-9a-zåäö]+", "", (s or "").lower())[:40]


def main():
    if not os.path.exists(XLSX):
        os.makedirs(SCRATCH, exist_ok=True)
        rc.download(URL, XLSX)
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="se")
    groups = {}   # (kind, kommun, operator) -> info
    for kind, sheet in (("housing", "Bostad med särskild serv, enhet"), ("day", "Daglig verksamhet, enhet ")):
        for kod, kommun, lan, namn, regi, utf, typ, *_ in rows(wb, sheet):
            kommun = rc.clean(kommun)
            if regi and str(regi).lower().startswith("offentlig"):
                op = f"{kommun} kommun"
            else:
                utf = rc.clean(utf)
                op = utf if utf and ORG_FORM.search(utf) else "Private provider"
            g = groups.setdefault((kind, kommun, op), {"kod": str(kod), "lan": re.sub(r"^\d+\s*", "", rc.clean(lan)), "n": 0, "names": [], "types": set()})
            g["n"] += 1
            g["types"].add(rc.clean(typ))
            if kind == "day":
                g["names"].append(rc.clean(namn))
    entries, nogeo = [], 0
    for (kind, kommun, op), g in groups.items():
        hit = geoc.geocode(f"{kommun}, {g['lan']}, Sweden")
        if not hit or not rc.plausible("SE", hit[0], hit[1]):
            hit = geoc.geocode(f"{kommun}, Sweden")
        if not hit or not rc.plausible("SE", hit[0], hit[1]):
            nogeo += 1
            continue
        if kind == "housing":
            forms = " and ".join(sorted(t.lower() for t in g["types"] if t))
            name = f"{op} - LSS housing for people with disabilities, {kommun}"
            desc = (f"{g['n']} {'unit' if g['n'] == 1 else 'units'} of housing with special service under the Swedish LSS act ({forms}) run by {op} in {kommun}. "
                    "Shown at municipality level; individual homes are not published here.")
            e = rc.entry(name, SOURCE, "social", ["Residential & Social Care"], desc, address=f"{kommun}, {g['lan']}, Sweden", lat=hit[0], lng=hit[1],
                         external_id=f"se-lss-bostad:{g['kod']}:{slug(op)}", scope="general")
        else:
            names = "; ".join(sorted(set(g["names"]))[:12]) + ("; ..." if len(set(g["names"])) > 12 else "")
            name = f"{op} - LSS day activity, {kommun}"
            desc = (f"{g['n']} day-activity {'unit' if g['n'] == 1 else 'units'} (daglig verksamhet under LSS) run by {op} in {kommun}: {names}. "
                    "Shown at municipality level; street addresses are not in the open data.")
            e = rc.entry(name, SOURCE, "social", ["Day Programs"], desc, address=f"{kommun}, {g['lan']}, Sweden", lat=hit[0], lng=hit[1],
                         external_id=f"se-lss-dagligverksamhet:{g['kod']}:{slug(op)}", scope="general")
        entries.append(e)
    print(f"{len(groups)} (municipality, operator) groups from {sum(g['n'] for g in groups.values())} units; {nogeo} without a geocode")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_sweden_lss.json"), entries)
    rc.spot_check(out, 30, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
