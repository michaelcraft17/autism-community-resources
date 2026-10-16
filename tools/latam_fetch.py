#!/usr/bin/env python3
"""
Latin America -- Mexico (SAT authorised donees) and Colombia (RUES non-profits on datos.gov.co).

Mexico   SAT "Directorio de Donatarias Autorizadas 2026" (xlsx, header on row 28). Active taxpayers only; one entry per RFC.
         Core = name matches autism / disability terms (or the authorised purpose mentions autism / Asperger); the 8.5k rows that
         merely list disability among many groups in their purpose text are NOT merged. REPRESENTANTE LEGAL and e-mail are never
         read. The fiscal address is often a private address, so entries are placed at the city of the SAT regional office (not published at street level).
Colombia https://www.datos.gov.co/resource/c82u-588k.json (RUES/Confecamaras). Active non-profits whose name matches autism /
         disability terms; the register has NO street address, so entries are placed at the chamber-of-commerce city.
         representante_legal / identification numbers are never read.
Output: new_resources_mexico.json, new_resources_colombia.json
"""
import json
import os
import re
import sys
import urllib.parse

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "world_small_scratch")
MX_RE = re.compile(r"(?<![a-záéíóúñ])autis|asperger|discapacit|s[ií]ndrome de down|par[aá]lisis cerebral|\bsordos?\b|\bciegos?\b|invidente|ceguera|sordera|"
                   r"\bTDAH\b|d[eé]ficit de atenci|espectro|neurodes|educaci[oó]n especial|necesidades especiales|\bAPAC\b|\bapac\b|inclusi[oó]n|capacidades diferentes|"
                   r"\bdiferentes capacidades|\bdown\b|epilep|distrofia muscular|espina b[ií]fida|psicomotr|lesi[oó]n medular|neuromotor|hipoacus", re.I)
MX_PURPOSE = re.compile(r"(?<![a-záéíóúñ])autis|asperger", re.I)
BAD = re.compile(r"bautis|flautist|ancianos|asilo|adultos mayores|inclusi[oó]n financiera|inclusi[oó]n social y econ|banco|transpor", re.I)
CO_RE = re.compile(r"(?<![a-záéíóúñ])autis|asperger|discapacid|s[ií]ndrome de down|par[aá]lisis cerebral|\bsordos?\b|\bciegos?\b|invidente|"
                   r"necesidades especiales|capacidades diferentes|diversidad funcional|inclusi[oó]n|especial", re.I)
CO_BAD = re.compile(r"bautis|flautist|financier|inversi|seguros|cooperativ", re.I)
STATE = {"Ciudad de México": "Mexico City", "Distrito Federal": "Mexico City"}


def smart(s):
    s = rc.clean(s)
    return s.title() if s.isupper() else s


def mexico():
    ws = openpyxl.load_workbook(os.path.join(SCRATCH, "mx.xlsx"), read_only=True).worksheets[0]
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache_mx.jsonl"), countrycodes="mx")
    seen, out, nogeo = set(), [], 0
    for r in ws.iter_rows(min_row=29, values_only=True):
        if not r or not r[3] or not r[4] or r[3] in seen:
            continue
        ent, rfc, name, addr, purpose, phone, status = r[0], r[3], rc.clean(r[4]), rc.clean(r[5]), rc.clean(r[8]), rc.clean(r[10]), rc.clean(r[14])
        if status != "Activo" or BAD.search(name):
            continue
        autism = MX_PURPOSE.search(name) or MX_PURPOSE.search(purpose[:1500])
        if not (MX_RE.search(name) or autism):
            continue
        seen.add(rfc)
        state = rc.clean(ent)
        city = re.sub(r"\s*\d+\s*$", "", rc.clean(r[1]))     # SAT regional office city, e.g. "Aguascalientes 1"
        hit = geoc.geocode(f"{city}, {state}, México") or geoc.geocode(f"{state}, México")
        if not hit or not rc.plausible("MX", *hit):
            nogeo += 1
            continue
        tel = re.sub(r"[^\d+ ()-]", "", phone)
        out.append(rc.entry(smart(re.sub(r",\s*(A\.?C\.?|I\.?A\.?P\.?|A\.?B\.?P\.?)$", "", name, flags=re.I)) if False else smart(name), "Mexico SAT directory of authorised donees (Donatarias Autorizadas 2026)",
                            "advocacy", ["Advocacy", "Information & Support"],
                            "Authorised donee (tax-deductible non-profit) " + ("working with autism." if autism else "with a disability-related name."),
                            address=", ".join(dict.fromkeys(x for x in (city, state, "México") if x)), phone=tel or None, lat=hit[0], lng=hit[1],
                            external_id=f"mx-rfc:{rfc}", scope=None if autism else "general"))
    print(f"Mexico: {len(out)} entries, {nogeo} without a geocode")
    return out


def colombia():
    path = os.path.join(SCRATCH, "co_rows.json")
    if os.path.exists(path):
        rows = json.load(open(path))
    else:
        words = ["AUTIS", "ASPERGER", "DISCAPACIDAD", "DOWN", "PARALISIS CEREBRAL", "SORDOS", "CIEGOS", "INVIDENTE", "NECESIDADES ESPECIALES", "CAPACIDADES DIFERENTES", "ESPECIAL"]
        rows = {}
        for w in words:
            where = (f"razon_social like '%{w}%' AND estado_matricula='ACTIVA' AND categoria_matricula='SOCIEDAD ó PERSONA JURIDICA PRINCIPAL ó ESAL' "
                     "AND tipo_sociedad='ENTIDAD SIN ANIMO DE LUCRO'")
            q = urllib.parse.urlencode({"$where": where, "$limit": 5000, "$select": "razon_social,camara_comercio,matricula,nit,tipo_sociedad,estado_matricula"})
            for x in json.loads(rc.get("https://www.datos.gov.co/resource/c82u-588k.json?" + q, timeout=180, delay=0.5)):
                rows[x["matricula"] + x["camara_comercio"]] = x
        rows = list(rows.values())
        json.dump(rows, open(path, "w"), ensure_ascii=False)
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache_co.jsonl"), countrycodes="co")
    out, nogeo = [], 0
    for x in rows:
        name = rc.clean(x["razon_social"])
        if not CO_RE.search(name) or CO_BAD.search(name) or re.search(r"liquidaci", name, re.I):
            continue
        if re.search(r"inclusi[oó]n|especial", name, re.I) and not re.search(r"discapac|autis|necesidades|diferentes|down|sordo|ciego|cognitiv|educaci[oó]n especial", name, re.I):
            continue
        city = smart(x["camara_comercio"])
        hit = geoc.geocode(f"{city}, Colombia")
        if not hit or not rc.plausible("CO", *hit):
            nogeo += 1
            continue
        autism = re.search(r"(?<![a-záéíóúñ])autis|asperger", name, re.I)
        out.append(rc.entry(smart(name), "Colombia RUES / Confecamaras non-profit registry (datos.gov.co)", "advocacy", ["Advocacy", "Information & Support"],
                            f"Registered non-profit ({city} chamber of commerce) with a disability-related name. The register has no street address; shown at city level.",
                            address=f"{city}, Colombia", lat=hit[0], lng=hit[1], external_id=f"co-nit:{x.get('nit')}:{x['camara_comercio']}",
                            scope=None if autism else "general"))
    print(f"Colombia: {len(out)} entries, {nogeo} without a geocode")
    return out


def main():
    a = rc.finalize(os.path.join(rc.REPO, "new_resources_mexico.json"), mexico())
    b = rc.finalize(os.path.join(rc.REPO, "new_resources_colombia.json"), colombia())
    rc.spot_check(a, 25, fields=("name", "address"))
    rc.spot_check(b, 20, fields=("name", "address"))


if __name__ == "__main__":
    main()
