#!/usr/bin/env python3
"""
Argentina -- Padron Oficial de Establecimientos Educativos (Ministerio de Capital Humano / DIE-ICSE, CC BY 4.0), the national
register of every school, as one XLSX:
    https://www.argentina.gob.ar/sites/default/files/2026.06.16_padron_oficial_establecimientos_educativos_die_icse.xlsx
Usage: python3 tools/argentina_padron_fetch.py [url]

Core: establishments flagged "Especial" (special-education modality), ~2,000 rows; the id is the Cueanexo (school +
annex code). Sub-columns give the levels offered (early stimulation, kindergarten, primary, secondary, integration support).
The Mail column is not read. Address geocoded with Nominatim (street + locality + province); when the street is not
found, the keyless official georef API (apis.datos.gob.ar/georef, cache georef_cache.jsonl) is tried, and its match is
accepted only if its locality or department is the padron's own and it lies within 25 km of the locality centre. Last
resort is the locality centre; the fallback is counted. prior_coords is deliberately not used: it would keep old locality pins. The cache is tools/argentina_padron_scratch/geocode_cache.jsonl,
so an interrupted run resumes. Output: new_resources_argentina_padron.json
"""
import json
import math
import os
import re
import sys
import unicodedata
import urllib.parse

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "argentina_padron_scratch")
URL = "https://www.argentina.gob.ar/sites/default/files/2026.06.16_padron_oficial_establecimientos_educativos_die_icse.xlsx"
SOURCE = "Argentina Padron Oficial de Establecimientos Educativos (special education)"
LEVELS = {24: ("early stimulation", "Early Intervention"), 25: ("kindergarten", "Special Education"), 26: ("primary", "Special Education"),
          27: ("secondary", "Special Education"), 28: ("integration support for mainstream schools", "Inclusion Support")}


GEOREF = "https://apis.datos.gob.ar/georef/api/direcciones?"


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def km(a, b):
    dx, dy = (a[1] - b[1]) * math.cos(math.radians(a[0])), a[0] - b[0]
    return 111.2 * math.hypot(dx, dy)


class Georef:
    """Official street-level geocoder; results (including misses) cached. A failed call is not cached."""

    def __init__(self, path):
        self.path, self.cache = path, {}
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                d = json.loads(line)
                self.cache[d["q"]] = d["c"]

    def find(self, street, prov, loc, dept, near):
        if not street:
            return None
        key = f"{street}|{prov}|{loc}|{dept}"
        if key not in self.cache:
            try:
                d = json.loads(rc.get(GEOREF + urllib.parse.urlencode({"direccion": street, "provincia": prov, "max": 5}), delay=0.15, timeout=30))
            except Exception as e:  # noqa: BLE001
                rc.note_failure("georef", f"{street}: {e!r}")
                return None
            want = {norm(loc), norm(dept)} - {""}
            c = None
            for x in d.get("direcciones", []):
                got = {norm(x["localidad_censal"]["nombre"]), norm(x["departamento"]["nombre"])}
                if got & want and x.get("ubicacion") and x["ubicacion"].get("lat") is not None:
                    c = [x["ubicacion"]["lat"], x["ubicacion"]["lon"]]
                    break
            self.cache[key] = c
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"q": key, "c": c}) + "\n")
        c = self.cache[key]
        if c and (not rc.plausible("AR", *c) or (near and km(c, near) > 25)):
            return None
        return tuple(c) if c else None


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
    georef = Georef(os.path.join(SCRATCH, "georef_cache.jsonl"))
    out, nogeo, coarse, failed, upgraded = [], 0, 0, 0, 0
    for r in sp:
        cue = str(r[7]).strip()
        prov, loc, dept = rc.clean(r[0]), smart(r[5] or ""), smart(r[3] or "")
        street = rc.clean(re.sub(r"\s+", " ", str(r[9] or "")))
        if prov == "Ciudad de Buenos Aires":
            prov, loc = "Ciudad Autonoma de Buenos Aires", "Buenos Aires"
        hit, is_coarse = None, False
        has_street = street and not re.fullmatch(r"(S/?N|SIN .*|-)", street, re.I)
        if has_street:
            hit = geoc.geocode(f"{street}, {loc}, {prov}, Argentina")
            if not hit and not geoc.last_failed:
                near = geoc.geocode(f"{loc}, {dept}, {prov}, Argentina") or geoc.geocode(f"{loc}, {prov}, Argentina")
                hit = georef.find(street, prov, loc, dept, near)
                upgraded += bool(hit)
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
    print(f"{len(sp)} special-education establishments; {len(out)} located ({coarse} at locality level, {upgraded} placed by georef); {nogeo} implausible/no geocode; {failed} lookups failed (retry later)")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_argentina_padron.json"), out)
    rc.spot_check(fin, 25, fields=("name", "address"))


if __name__ == "__main__":
    main()
