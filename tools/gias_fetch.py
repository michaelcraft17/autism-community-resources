#!/usr/bin/env python3
"""
England (and Wales) special schools and mainstream SEN units from GIAS -- the Department for Education's
"Get Information About Schools" register (Open Government Licence v3), one keyless CSV:

    https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata<YYYYMMDD>.csv

The filename date changes daily and the newest snapshots are sometimes still being written (on 2026-10-12
the 20261011/20261012 files were 39-48 MB against a full 64.7 MB), so this takes an explicit date:
`python3 tools/gias_fetch.py 20261010`. A snapshot with fewer than 50,000 rows is rejected.

Sets (open establishments only; cp1252 CSV):
  core   all special schools / special post-16 institutions (EstablishmentTypeGroup "Special schools" or a
         type containing "special"), plus mainstream schools with an SEN unit or resourced provision whose
         SEN1-13 fields include ASD (autism)
  broad  mainstream schools with an SEN unit / resourced provision that does NOT list ASD (hearing, vision,
         physical, learning units, ...) -> new_resources_gias_broad.json, merged separately
Pupil referral units are alternative provision rather than SEN provision and are not included.

Coordinates are British National Grid (EPSG:27700), converted with pyproj. Head teacher fields
(HeadFirstName/HeadLastName) are never read. Entries are disability_scope "general" (special schools serve
every need); the services list says "Autism Support" where ASD is a listed need.

Writes:
    tools/gias_scratch/edubase_<date>.csv    raw download (gitignored)
    new_resources_gias.json                  core
    new_resources_gias_broad.json            broad
"""
import csv
import os
import sys

from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "gias_scratch")
SOURCE = "England GIAS (DfE Get Information About Schools) - official register of schools, Open Government Licence"
BNG = Transformer.from_crs(27700, 4326, always_xy=True)
UNIT_TYPES = {"Resourced provision", "SEN unit", "Resourced provision and SEN unit"}


def sen_needs(r):
    return [r[f"SEN{i} (name)"].split(" - ")[0].strip() for i in range(1, 14)
            if r.get(f"SEN{i} (name)") and r[f"SEN{i} (name)"] != "Not Applicable"]


def build(rows):
    core, broad = [], []
    for r in rows:
        if not r["EstablishmentStatus (name)"].startswith("Open"):
            continue
        special = r["EstablishmentTypeGroup (name)"] == "Special schools" or "special" in r["TypeOfEstablishment (name)"].lower()
        unit = r["TypeOfResourcedProvision (name)"] in UNIT_TYPES
        if not (special or unit):
            continue
        needs = sen_needs(r)
        asd = "ASD" in needs
        if not r["Easting"] or not r["Northing"]:
            continue
        lng, lat = BNG.transform(float(r["Easting"]), float(r["Northing"]))
        if not rc.plausible("GB", lat, lng):
            continue
        addr = ", ".join(rc.clean(r[k]) for k in ("Street", "Locality", "Town", "Postcode") if rc.clean(r[k]))
        kind = r["TypeOfEstablishment (name)"]
        ages = f", ages {r['StatutoryLowAge']}-{r['StatutoryHighAge']}" if r["StatutoryLowAge"] and r["StatutoryHighAge"] else ""
        if special:
            desc = f"{kind}{ages}."
        else:
            prov = r["TypeOfResourcedProvision (name)"].lower()
            desc = f"Mainstream school ({kind}) with an {prov}{ages}." if prov == "sen unit" else \
                   f"Mainstream school ({kind}) with {prov}{ages}."
        if needs:
            desc += " Needs catered for: " + ", ".join(needs) + "."
        services = ["Special Education"] + (["Autism Support"] if asd else [])
        e = rc.entry(r["EstablishmentName"], SOURCE, "education", services, desc, address=addr,
                     phone=r["TelephoneNum"], website=rc.clean_url(r["SchoolWebsite"]), lat=lat, lng=lng,
                     external_id=f"gias:{r['URN']}", breadth="core" if (special or asd) else "broad", scope="general")
        (core if e["breadth"] == "core" else broad).append(e)
    return core, broad


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "20261010"
    path = rc.download(f"https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata{date}.csv",
                       os.path.join(SCRATCH, f"edubase_{date}.csv"))
    with open(path, encoding="cp1252", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) < 50000:
        sys.exit(f"{date}: only {len(rows)} rows -- partial snapshot, pick another date")
    core, broad = build(rows)
    print(f"GIAS {date}: {len(rows)} rows -> core {len(core)}, broad {len(broad)}")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_gias.json"), core)
    rc.finalize(os.path.join(rc.REPO, "new_resources_gias_broad.json"), broad)
    rc.spot_check(out, 10, fields=("name", "address", "services"))


if __name__ == "__main__":
    main()
