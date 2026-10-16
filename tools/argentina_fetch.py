#!/usr/bin/env python3
"""
Argentina -- IGJ (Inspeccion General de Justicia) entities, datos.jus.gob.ar (CC BY 4.0), latest semester zip.
Only igj-entidades-*.csv and igj-domicilios-*.csv are read (the "autoridades" file lists named officers and is never opened).

Core: asociacion civil (type 100) / fundacion (110) entities not dada_de_baja whose name matches autism / disability terms.
Companies (e.g. "AUTISIMA SRL", type 40) are excluded. IGJ covers the City of Buenos Aires plus national-scope entities.
Legal address geocoded with Nominatim (street, then locality). Output: new_resources_argentina.json
"""
import csv
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "world_small_scratch", "igj")
RE = re.compile(r"(?<![A-ZÁÉÍÓÚÑ])AUTIS(?!IM|SIM)|ASPERGER|DISCAPAC|SINDROME DE DOWN|S[IÍ]NDROME DE DOWN|PARALISIS CEREBRAL|PAR[AÁ]LISIS CEREBRAL|\bSORDOS?\b|\bCIEGOS?\b|"
                r"NECESIDADES ESPECIALES|CAPACIDADES DIFERENTES|\bTEA\b|\bTDAH\b|DEFICIT DE ATENCION|D[EÉ]FICIT DE ATENCI|\bDOWN\b|NEURODIVERS|INTEGRACION DE PERSONAS|"
                r"PERSONAS CON (CAPACIDADES|NECESIDADES)|PSICOMOTR|LESION MEDULAR|ESPINA BIFIDA|EPILEPSIA|HIPOACUS|\bAPADEA\b|\bFADEA\b", re.I)
BAD = re.compile(r"BAUTIS|FLAUTIS|AUTISIM|AUTISSIM|CRIADORES|HAMPSHIRE|GANAD|OVINO|BOVINO|CABALL|SPORT CLUB", re.I)


def smart(s):
    s = rc.clean(s)
    return s.title() if s.isupper() else s


def main():
    ent = sorted(glob.glob(os.path.join(SCRATCH, "igj-entidades-*.csv")))[-1]
    dom = sorted(glob.glob(os.path.join(SCRATCH, "igj-domicilios-*.csv")))[-1]
    cand = {}
    for r in csv.DictReader(open(ent, encoding="utf-8-sig", errors="replace")):
        if r["tipo_societario"] not in ("100", "110") or r["dada_de_baja"] or BAD.search(r["razon_social"]) or not RE.search(r["razon_social"]):
            continue
        cand[r["numero_correlativo"]] = r
    addr = {}
    for r in csv.DictReader(open(dom, encoding="utf-8-sig", errors="replace")):
        if r["numero_correlativo"] in cand and r["tipo_domicilio"] == "L":
            addr[r["numero_correlativo"]] = r
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="ar")
    out, nogeo = [], 0
    for k, r in cand.items():
        a = addr.get(k)
        if not a:
            continue
        loc, prov = rc.clean(a["localidad"]), rc.clean(a["provincia"])
        street = f"{rc.clean(a['calle'])} {rc.clean(a['numero'])}".strip()
        hit = geoc.geocode(f"{street}, {loc}, {prov}, Argentina") if street and not re.match(r"(S/N|SIN )", street, re.I) else None
        hit = hit or geoc.geocode(f"{loc}, {prov}, Argentina" if prov else f"{loc}, Argentina")
        if not hit or not rc.plausible("AR", *hit):
            nogeo += 1
            continue
        name = smart(r["razon_social"])
        autism = re.search(r"(?<![A-Z])AUTIS|ASPERGER|\bTEA\b|APADEA|FADEA", r["razon_social"])
        out.append(rc.entry(name, "Argentina IGJ entities register (datos.jus.gob.ar)", "advocacy", ["Advocacy", "Information & Support"],
                            f"Registered {r['descripcion_tipo_societario'].lower()} (IGJ) with a disability-related name.",
                            address=", ".join(x for x in (smart(street), smart(loc), smart(prov), "Argentina") if x), lat=hit[0], lng=hit[1],
                            external_id=f"ar-igj:{k}", scope=None if autism else "general"))
    print(f"{len(cand)} candidates, {len(addr)} with a legal address; {len(out)} entries; {nogeo} without a geocode")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_argentina.json"), out)
    rc.spot_check(fin, 20, fields=("name", "address"))


if __name__ == "__main__":
    main()
