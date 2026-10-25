#!/usr/bin/env python3
"""
Argentina -- Padron Oficial de Establecimientos Educativos (Ministerio de Capital Humano / DIE-ICSE, CC BY 4.0), the national
register of every school, as one XLSX:
    https://www.argentina.gob.ar/sites/default/files/2026.06.16_padron_oficial_establecimientos_educativos_die_icse.xlsx
Usage: python3 tools/argentina_padron_fetch.py [url]

Core: establishments flagged "Especial" (special-education modality), ~2,000 rows; the id is the Cueanexo (school +
annex code). Sub-columns give the levels offered (early stimulation, kindergarten, primary, secondary, integration support).
The Mail column is not read. Address geocoded with Nominatim (street + locality + province), falling back to the
locality when the street is not found; the fallback is counted. The cache is tools/argentina_padron_scratch/geocode_cache.jsonl,
so an interrupted run resumes. Output: new_resources_argentina_padron.json
"""
import os
import re
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "argentina_padron_scratch")
URL = "https://www.argentina.gob.ar/sites/default/files/2026.06.16_padron_oficial_establecimientos_educativos_die_icse.xlsx"
SOURCE = "Argentina Padron Oficial de Establecimientos Educativos (special education)"
LEVELS = {24: ("early stimulation", "Early Intervention"), 25: ("kindergarten", "Special Education"), 26: ("primary", "Special Education"),
          27: ("secondary", "Special Education"), 28: ("integration support for mainstream schools", "Inclusion Support")}


def smart(s):
    s = rc.clean(s)
    letters = [c for c in s if c.isalpha() and c.lower() != c.upper()]
    shouty = letters and sum(c.isupper() for c in letters) / len(letters) > 0.8   # "Nº" has a lowercase letter
    return re.sub(r"\bNº\s*", "Nº ", s.title()) if shouty or s.islower() else s


def main():
    path = rc.download(sys.argv[1] if len(sys.argv) > 1 else URL, os.path.join(SCRATCH, "padron.xlsx"))
    rows = [list(r) + [None] * (30 - len(r)) for r in openpyxl.load_workbook(path, read_only=True).active.iter_rows(values_only=True)]
    h = next(i for i, r in enumerate(rows) if r[7] == "Cueanexo")
    sp = [r for r in rows[h + 1:] if r[14] == 1 and r[7] and r[8]]
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="ar")
    out, nogeo, coarse, failed = [], 0, 0, 0
    for r in sp:
        cue = str(r[7]).strip()
        prov, loc, dept = rc.clean(r[0]), smart(r[5] or ""), smart(r[3] or "")
        street = rc.clean(re.sub(r"\s+", " ", str(r[9] or "")))
        if prov == "Ciudad de Buenos Aires":
            prov, loc = "Ciudad Autonoma de Buenos Aires", "Buenos Aires"
        cached = rc.prior_coords(f"ar-padron:{cue}", ", ".join(x for x in (street.title(), loc, prov, "Argentina") if x))
        hit, is_coarse = cached, False
        if not hit and street and not re.fullmatch(r"(S/?N|SIN .*|-)", street, re.I):
            hit = geoc.geocode(f"{street}, {loc}, {prov}, Argentina")
        if not hit and not geoc.last_failed:
            hit, is_coarse = geoc.geocode(f"{loc}, {dept}, {prov}, Argentina") or geoc.geocode(f"{loc}, {prov}, Argentina"), True
        if geoc.last_failed and not hit:
            failed += 1
            continue
        if not hit or not rc.plausible("AR", *hit):
            nogeo += 1
            continue
        coarse += is_coarse
        lv = [(t, s) for c, (t, s) in LEVELS.items() if r[c] == 1]
        services = list(dict.fromkeys(["Special Education"] + [s for _, s in lv]))
        sector = {"Estatal": "public", "Privado": "private"}.get(rc.clean(r[1]), rc.clean(r[1]).lower())
        desc = (f"Special-education school ({sector} sector, CUE-anexo {cue})"
                + (f" offering {', '.join(t for t, _ in lv)}" if lv else "") + ".")
        phone = rc.clean(r[11]) or None
        addr = ", ".join(x for x in (smart(street), loc, prov.replace("Ciudad Autonoma de Buenos Aires", "Ciudad de Buenos Aires"), "Argentina") if x)
        out.append(rc.entry(smart(r[8]), SOURCE, "education", services, desc, address=addr, phone=phone, lat=hit[0], lng=hit[1],
                            external_id=f"ar-padron:{cue}", scope="general"))
    print(f"{len(sp)} special-education establishments; {len(out)} located ({coarse} at locality level); {nogeo} implausible/no geocode; {failed} lookups failed (retry later)")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_argentina_padron.json"), out)
    rc.spot_check(fin, 25, fields=("name", "address"))


if __name__ == "__main__":
    main()
