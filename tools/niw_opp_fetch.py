#!/usr/bin/env python3
"""
Poland -- NIW-CRSO list of public-benefit organisations (OPP) eligible for 1.5% of income tax.

Page:  https://niw.gov.pl/opp/wykaz-opp  (links the yearly xlsx; the catalog= id changes, read it from the page)
File:  https://niw.gov.pl/opp/wykaz-opp/?export=XLSX&data_scope=all&catalog=<id>   keyless; header on row 4:
       LP, KRS, NIP, Nazwa OPP, Wojewodztwo, Powiat, Gmina, Miejscowosc.

Selection: names matching the disability regex from the round-6 notes (core) and rehabilitation/therapy/psychiatry
words (broad). Associations and foundations without premises in the list: the location is the town only (no street),
geocoded with Nominatim (cached) and shown as "town, voivodeship". Key = KRS.
Output: new_resources_niw_opp.json (core), new_resources_niw_opp_broad.json (broad).
"""
import os
import re
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "niw_scratch")
PAGE = "https://niw.gov.pl/opp/wykaz-opp"
SOURCE = "Poland NIW-CRSO public-benefit organisations list (OPP)"
CORE_RE = re.compile(
    r"autyz|asperger|niep\w*łnospraw|inwalid|upośledz|intelektualn|porażen\w* mózg|zespo\w* down|głuch|niesłysz|słabosłysz|niewidom|"
    r"słabowid|ociemn|tyflo|surdo|rewalid|specjalnej troski|szk\w* specjaln|warsztat\w* terapii|\bwtz\b|dom\w* samopomocy|epilep|"
    r"stwardnien|dystrofi|rdzeni|amputa|wózk|adhd|dysleks|olimpiad\w* specjaln|paraolimp|sprawni inaczej", re.I)
BROAD_RE = re.compile(r"rehabilit|terapi|psychiatr|zdrowia psychicznego|integracyjn", re.I)
VOIVODESHIP = {"DOLNOŚLĄSKIE": "Lower Silesia", "KUJAWSKO-POMORSKIE": "Kuyavia-Pomerania", "LUBELSKIE": "Lublin", "LUBUSKIE": "Lubusz",
               "ŁÓDZKIE": "Łódź", "MAŁOPOLSKIE": "Lesser Poland", "MAZOWIECKIE": "Masovia", "OPOLSKIE": "Opole", "PODKARPACKIE": "Subcarpathia",
               "PODLASKIE": "Podlaskie", "POMORSKIE": "Pomerania", "ŚLĄSKIE": "Silesia", "ŚWIĘTOKRZYSKIE": "Świętokrzyskie",
               "WARMIŃSKO-MAZURSKIE": "Warmia-Masuria", "WIELKOPOLSKIE": "Greater Poland", "ZACHODNIOPOMORSKIE": "West Pomerania"}


def titlecase(s):
    return rc.clean(s).title()


def main():
    path = os.path.join(SCRATCH, "opp.xlsx")
    if not os.path.exists(path):
        os.makedirs(SCRATCH, exist_ok=True)
        page = rc.get(PAGE, browser=True).decode("utf-8", "replace")
        m = re.search(r"export=XLSX&(?:amp;)?data_scope=all&(?:amp;)?catalog=(\d+)", page)
        rc.download(f"{PAGE}/?export=XLSX&data_scope=all&catalog={m.group(1)}", path, browser=True)
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="pl")
    out = {"core": [], "broad": []}
    nogeo = 0
    for r in list(ws.iter_rows(values_only=True))[4:]:
        if not r[1] or not r[3]:
            continue
        name = rc.clean(r[3])
        tier = "core" if CORE_RE.search(name) else ("broad" if BROAD_RE.search(name) else None)
        if not tier:
            continue
        krs, voiv, powiat, gmina, town = str(r[1]).zfill(10), rc.clean(r[4]), rc.clean(r[5]), rc.clean(r[6]), titlecase(r[7])
        hit = geoc.geocode(f"{town}, {voiv.title()} voivodeship, Poland") or geoc.geocode(f"{town}, Poland")
        if not hit or not rc.plausible("PL", *hit):
            nogeo += 1
            continue
        typ = "therapy" if (tier == "broad" and re.search(r"rehabilit|terapi", name, re.I)) else "advocacy"
        services = ["Therapy"] if typ == "therapy" else ["Advocacy", "Information & Support"]
        out[tier].append(rc.entry(titlecase(name) if name.isupper() else name, SOURCE, typ, services,
                                  "Public-benefit organisation (OPP) with a disability-related name or purpose; location shown at town level.",
                                  address=f"{town}, {VOIVODESHIP.get(voiv, voiv.title())}, Poland", lat=hit[0], lng=hit[1],
                                  external_id=f"pl-krs:{krs}", breadth=tier,
                                  scope=None if re.search(r"autyz|asperger", name, re.I) else "general"))
    print(f"core {len(out['core'])}, broad {len(out['broad'])}, without a geocode {nogeo}")
    core = rc.finalize(os.path.join(rc.REPO, "new_resources_niw_opp.json"), out["core"])
    rc.finalize(os.path.join(rc.REPO, "new_resources_niw_opp_broad.json"), out["broad"])
    rc.spot_check(core, 30, fields=("name", "address"))


if __name__ == "__main__":
    main()
