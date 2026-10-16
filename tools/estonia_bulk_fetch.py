#!/usr/bin/env python3
"""
Estonia -- e-Business Register (Äriregister, RIK) open-data bulk "lihtandmed" (basic data) file.

Source: https://avaandmed.ariregister.rik.ee/sites/default/files/avaandmed/ettevotja_rekvisiidid__lihtandmed.csv.zip
(refreshed daily, ~18 MB zip, UTF-8 with BOM, ';'-separated). The host sits behind Cloudflare and answers 429 (code
1015) after one or two downloads -- download once, keep the zip in tools/estonia_scratch/, wait 10-15 minutes
before the next file if more are ever needed.

Selection (round-6 notes, E1): registered entities (staatus R) whose name matches the disability regex. Core =
disability regex; broad = care/rehab/support words (rehabilitatsioon, tugikeskus, paevakeskus, logopeed ...).
Excluded legal forms: Korteriühistu / Hooneühistu (apartment associations -- street names like "Invaliidi tn")
and FIE (sole traders: the name is a person's name). Registry codes (ariregistri_kood) are the external id.
The EMTAK-code tier (87201 etc.) lives in the 4.6 GB "yldandmed" file and is not fetched here.

Geocoding: Maa-amet in-ADS gazetteer (official), on the normalised ADS address; entries it cannot place are dropped.

Output: new_resources_estonia_bulk.json (core), new_resources_estonia_bulk_broad.json (broad).
Dedupe against the 55 existing Estonia entries happens in merge_new_resources.py (name + city).
"""
import csv
import io
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "estonia_scratch")
ZIP = os.path.join(SCRATCH, "lihtandmed.csv.zip")
URL = "https://avaandmed.ariregister.rik.ee/sites/default/files/avaandmed/ettevotja_rekvisiidid__lihtandmed.csv.zip"
SOURCE = "Estonia e-Business Register (Ariregister, RIK) - official national entity registry"

CORE_RE = re.compile(
    r"\bautis|asperger|puue|puudega|puuetega|invaliid|erivajadus|\bkurt(ide)?\b|vaegkuulj|\bpimed(ate|ad)\b(?!\s+ööde)|vaegnägij|"
    r"nägemispuu|liikumispuu|intellektipuu|vaimupuu|downi sündroom|ajukahjust|tserebraal|epilepsia|tähelepanu|adhd|düsleks|"
    r"erihoolekan|viipekeel|special olympics|paraolümp|parasport", re.I)
NOT_RE = re.compile(r"bautista|nautis|rautis|pimedate ööde|\bkurt\s+[a-zõäöü]+\s+(osaühing|oü)\b", re.I)
BROAD_RE = re.compile(r"rehabilitatsioon|tugikeskus|päevakeskus|logopeed|eripedagoog|tugiisik|isikliku abistaja", re.I)
EXCLUDE_FORMS = {"Korteriühistu", "Hooneühistu", "Füüsilisest isikust ettevõtja", "FIE"}
ASSOC_FORMS = {"Mittetulundusühing", "Sihtasutus", "Usuline ühendus"}
COMMERCIAL_FORMS = {"Osaühing", "Aktsiaselts", "Täisühing", "Usaldusühing"}
SERVICE_RE = re.compile(r"erihoolekan|viipekeel|rehabilit|tugikeskus|päevakeskus|logopeed|eripedagoog|hoolekan|tugiisik|abistaja", re.I)
PEER_RE = re.compile(r"tugi|klubi|kogukond|pere", re.I)


def main():
    if not os.path.exists(ZIP):
        os.makedirs(SCRATCH, exist_ok=True)
        rc.download(URL, ZIP)
    zf = zipfile.ZipFile(ZIP)
    member = next(n for n in zf.namelist() if n.endswith(".csv"))
    rows = csv.DictReader(io.TextIOWrapper(zf.open(member), encoding="utf-8-sig"), delimiter=";")
    geoc = rc.MaaAmet(os.path.join(SCRATCH, "maaamet_cache.jsonl"))
    out = {"core": [], "broad": []}
    nogeo = excluded = 0
    for r in rows:
        if r["ettevotja_staatus"] != "R":
            continue
        name = r["nimi"]
        tier = "core" if CORE_RE.search(name) and not NOT_RE.search(name) else ("broad" if BROAD_RE.search(name) else None)
        if not tier:
            continue
        form = r["ettevotja_oiguslik_vorm"]
        if form in EXCLUDE_FORMS:
            excluded += 1
            continue
        if form in COMMERCIAL_FORMS and not SERVICE_RE.search(name):
            excluded += 1       # "Puuekspert OÜ", "Tähelepanu OÜ": a bare disability word in a company name is mostly not a service
            continue
        adr = r["ads_normaliseeritud_taisaadress"] or r["ettevotja_aadress"]
        hit = geoc.address(adr)
        if not hit or not rc.plausible("EE", *hit):
            nogeo += 1
            continue
        if tier == "broad":
            typ = "therapy" if re.search(r"logopeed|eripedagoog|rehabilitatsioon", name, re.I) else "general_support"
        else:
            typ = "advocacy" if form in ASSOC_FORMS and not PEER_RE.search(name) else "general_support"
        services = ["Advocacy", "Information & Support"] if typ == "advocacy" else (["Therapy"] if typ == "therapy" else ["Information & Support"])
        code = r["ariregistri_kood"]
        desc = f"{form} registered in the Estonian e-Business Register ({r['asukoha_ehak_tekstina'].split(',')[0]}); disability-related name or purpose."
        out[tier].append(rc.entry(name, SOURCE, typ, services, desc, address=f"{adr}, Estonia", website=None, lat=hit[0], lng=hit[1],
                                  external_id=f"ee:{code}", breadth=tier,
                                  scope=None if re.search(r"\bautis|asperger", name, re.I) else "general"))
    print(f"core {len(out['core'])}, broad {len(out['broad'])}; excluded legal forms {excluded}, no geocode {nogeo}")
    core = rc.finalize(os.path.join(rc.REPO, "new_resources_estonia_bulk.json"), out["core"])
    rc.finalize(os.path.join(rc.REPO, "new_resources_estonia_bulk_broad.json"), out["broad"])
    rc.spot_check(core, 30, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
