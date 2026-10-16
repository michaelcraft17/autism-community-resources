#!/usr/bin/env python3
"""
Spain -- three more regional registers (the earlier four are in spain_regional_fetch.py):

  Aragon  gd.aragon.es BRSCGI JSON, one call per province (BASE=ASHU/ASTE/ASSC, pages of 10,000 via DOCS=n-m). Rows whose
          "Tematica" is 027 MINUSVALIDOS, or whose name matches an autism / disability term. Active associations only
          (BAJA-C=S* filter in the URL).
  Castilla y Leon  datosabiertos.jcyl.es patient-associations directory (CSV, ';', Latin-1): AUTISMO, TDAH, DISCAPACIDAD
          (intelectual / fisica), PARALISIS CEREBRAL, SINDROME DE DOWN, plus epilepsy rows. Includes phone / e-mail / web.
  Valencia  dadesobertes.gva.es 2020 snapshot -- attempted; skipped when the host does not resolve (no workaround).
E-mail addresses are not published. Output: new_resources_aragon.json, new_resources_castilla_leon.json
"""
import csv
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "small_scratch")
AR_URL = ("https://gd.aragon.es/cgi-bin/AODB/BRSCGI?CMD=VERLST&OUTPUTMODE=JSON&BASE={b}&DOCS={d}&SEC=OPENDATAASHUJSON&SORT=DENO&SEPARADOR=&OP1=Y&DENO-C="
          "&OP2=Y&DOMI-C=&OP3=Y&LOCA-C=&OP4=Y&NUM-C=&OP5=Y&ANYO-C=&OP6=Y&FIN-C=&OP7=NO&UTIL-C=&OP10=Y&PROV-C={p}&OP8=NO&BAJA-C=S*&OP9=O&ANYO-C=")
CYL_URL = "https://datosabiertos.jcyl.es/web/jcyl/risp/es/salud/asociaciones-pacientes/1285022095152.csv"
NAME_RE = re.compile(
    r"(?<![a-záéíóúñ])autis|asperger|discapacit|minusv[aá]l|s[ií]ndrome de down|\bdown\b|par[aá]lisis cerebral|\bTDAH\b|d[eé]ficit de atenci|epilep|"
    r"\bsordo|\bsordos|\bciegos|invidente|\bdisminuid|diversidad funcional|trastorno del espectro|\bTEA\b|dislexia|espina b[ií]fida|distrofia muscular|"
    r"discapacidad intelectual|\bAFANAS|\bAPANID|\bFEAPS|\bPLENA INCLUSI[OÓ]N|\bATADES|\bADEMA\b|\bFAPAR\b|\bCERMI|\bO\.?N\.?C\.?E\b|\bfundaci[oó]n down", re.I)
BAD = re.compile(r"bautis", re.I)
CYL_CATS = ("AUTISMO", "TRASTORNO DE DÉFICIT", "PERSONAS CON DISCAPACIDAD", "PARÁLISIS CEREBRAL", "SÍNDROME DE DOWN", "NEUROLOGÍA", "ICTUS Y DAÑO CEREBRAL")


def smart(s):
    s = rc.clean(html.unescape(s))
    s = re.sub(r'^[\s"“”]+|[\s"“”]+$', "", s)
    return s.title().replace(" De ", " de ").replace(" Y ", " y ").replace(" Del ", " del ").replace(" La ", " la ").replace(" Para ", " para ") if s.isupper() else s


def aragon():
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache_es.jsonl"), countrycodes="es")
    out, nogeo, seen = [], 0, set()
    for base, prov in (("ASHU", "H"), ("ASTE", "T"), ("ASSC", "Z")):
        start = 1
        while True:
            path = os.path.join(SCRATCH, f"ar_{base}_{start}.json")
            if not os.path.exists(path):
                open(path, "wb").write(rc.get(AR_URL.format(b=base, d=f"{start}-{start + 9999}", p=prov), timeout=240, delay=1.0))
            rows = json.loads(open(path, "rb").read().decode("latin-1"), strict=False)
            if rows and "Numero_inscripcion" not in rows[0]:
                print(base, "unexpected keys", sorted(rows[0]))
            for r in rows:
                name, thema = html.unescape(r.get("Denominacion", "")), r.get("Tematica", "")
                num = r.get("Numero_inscripcion")
                if not num or not name:
                    continue
                if num in seen or BAD.search(name):
                    continue
                if not (re.match(r"\s*027", thema) or NAME_RE.search(name)):
                    continue
                seen.add(num)
                dom, loc = rc.clean(html.unescape(r.get("Domicilio", ""))), rc.clean(html.unescape(r.get("Localidad", "")))
                town = re.sub(r"^\d{5}\s*", "", loc)
                hit = geoc.geocode(f"{dom}, {loc}, Spain") if dom and not re.match(r"(UNICA|ÚNICA|S/N)", dom, re.I) else None
                hit = hit or geoc.geocode(f"{loc}, {'Zaragoza' if prov == 'Z' else 'Huesca' if prov == 'H' else 'Teruel'}, Spain")
                if not hit or not rc.plausible("ES", *hit):
                    nogeo += 1
                    continue
                out.append(rc.entry(smart(name), "Aragon register of associations (gd.aragon.es open data)", "advocacy",
                                    ["Advocacy", "Information & Support"], "Registered association in Aragon (disability category or disability-related name).",
                                    address=", ".join(x for x in (dom.title() if dom.isupper() else dom, loc, "Spain") if x), lat=hit[0], lng=hit[1],
                                    external_id=f"es-aragon:{num}", scope=None if re.search(r"(?<![a-z])autis|asperger", name, re.I) else "general"))
            if len(rows) < 10000:
                break
            start += 10000
    print(f"Aragon: {len(out)} entries, {nogeo} without a geocode")
    return out


def castilla_leon():
    path = os.path.join(SCRATCH, "cyl.csv")
    if not os.path.exists(path):
        rc.download(CYL_URL, path)
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache_es.jsonl"), countrycodes="es")
    out, nogeo = [], 0
    for r in list(csv.reader(open(path, encoding="latin-1"), delimiter=";"))[1:]:
        r = (r + [""] * 9)[:9]
        cat, name, prov, town, addr, phone, _mail, web, reg = (rc.clean(x) for x in r)
        if not name or not cat.upper().startswith(CYL_CATS):
            continue
        if cat.upper().startswith(("NEUROLOG", "ICTUS")) and not NAME_RE.search(name):
            continue
        hit = geoc.geocode(f"{addr}, {town}, {prov}, Spain") if addr else None
        hit = hit or geoc.geocode(f"{town}, {prov}, Spain")
        if not hit or not rc.plausible("ES", *hit):
            nogeo += 1
            continue
        autism = cat.upper().startswith("AUTISMO") or re.search(r"(?<![a-z])autis|asperger", name, re.I)
        web = web if not web or web.startswith("http") else "http://" + web
        out.append(rc.entry(smart(name), "Castilla y Leon patient associations directory (datosabiertos.jcyl.es)", "advocacy",
                            ["Advocacy", "Information & Support"], f"Patient / family association in Castilla y León (category: {cat.title()}).",
                            address=", ".join(dict.fromkeys(x for x in (addr, town, prov, "Spain") if x and x.lower() not in addr.lower().replace(".", ",")[:0])), phone=phone.split("/")[0].strip() or None,
                            website=rc.clean_url(web) if web else None, lat=hit[0], lng=hit[1],
                            external_id=f"es-cyl:{re.sub(r'[^A-Za-z0-9/]', '', reg)}:{re.sub(r'[^a-z0-9]', '', name.lower())[:30]}",
                            scope=None if autism else "general"))
    print(f"Castilla y Leon: {len(out)} entries, {nogeo} without a geocode")
    return out


def main():
    a = rc.finalize(os.path.join(rc.REPO, "new_resources_aragon.json"), aragon())
    b = rc.finalize(os.path.join(rc.REPO, "new_resources_castilla_leon.json"), castilla_leon())
    rc.spot_check(a, 20, fields=("name", "address"))
    rc.spot_check(b, 15, fields=("name", "address"))


if __name__ == "__main__":
    main()
