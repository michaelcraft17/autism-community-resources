#!/usr/bin/env python3
"""
France: disability establishments and services from FINESS, the national register of health and
social establishments (Etalab open licence), one keyless CSV with addresses AND coordinates:

    https://static.data.gouv.fr/resources/finess-extraction-du-fichier-des-etablissements/20260512-091152/etalab-cs1100507-stock-20260512-0339.csv
    (dataset: data.gouv.fr "finess-extraction-du-fichier-des-etablissements"; 'structureet' rows + 'geolocalisation' rows)

Selected by aggregate category (categagretab): 4101-4107 (education speciale / IME / ITEP / SESSAD / CMPP / CAMSP ...),
4301-4305 (adult disability: foyers, MAS, FAM, ESAT, SAVS/SAMSAH ...), 4609 (UEROS), plus MDPH (categetab 609)
and resource centres (categetab 461). CLIC (elderly), addiction and homeless services are not included.

Coordinates are projected metres -- Lambert-93 (EPSG:2154) for the mainland, the overseas departments' own
UTM/RGAF/RGR/RGFG/RGM grids -- converted with pyproj (the EPSG code is on each geolocalisation row).
Residential structures (foyers, MAS, FAM) are staffed institutions, so they are pinned at their address.
Rows are disability_scope "general". No person data in FINESS structureet rows is read.

Writes new_resources_finess.json (tools/finess_scratch/ holds the raw CSV, gitignored).
"""
import csv
import os
import re
import sys

from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "finess_scratch")
URL = "https://static.data.gouv.fr/resources/finess-extraction-du-fichier-des-etablissements/20260512-091152/etalab-cs1100507-stock-20260512-0339.csv"
SOURCE = "France FINESS (national register of health and social establishments) - Etalab open data"
AGG = {"4101", "4102", "4103", "4104", "4105", "4106", "4107", "4301", "4302", "4303", "4304", "4305", "4609"}
EXTRA_CAT = {"609": ("general_support", ["Information & Support"]),     # MDPH
             "461": ("general_support", ["Information & Support"])}     # resource centres
# aggregate category -> (type, services, kind)
AGG_MAP = {
    "4101": ("education", ["Special Education", "Habilitation"], "special-education establishment"),
    "4102": ("education", ["Special Education", "Habilitation"], "special-education establishment (behavioural difficulties)"),
    "4103": ("education", ["Special Education", "Rehabilitation"], "special-education establishment (motor disability)"),
    "4104": ("education", ["Special Education"], "special-education establishment (sensory disability)"),
    "4105": ("social", ["Residential & Social Care"], "residential establishment for children with disabilities"),
    "4106": ("therapy", ["Habilitation", "Early Intervention"], "outpatient or at-home service for children with disabilities"),
    "4107": ("education", ["Special Education"], "experimental establishment for children with disabilities"),
    "4301": ("social", ["Residential & Social Care"], "accommodation for adults with disabilities"),
    "4302": ("social", ["Employment Support"], "sheltered or supported work for adults with disabilities"),
    "4303": ("social", ["Employment Support", "Rehabilitation"], "vocational rehabilitation for adults with disabilities"),
    "4304": ("social", ["Residential & Social Care"], "experimental establishment for adults with disabilities"),
    "4305": ("social", ["Information & Support", "Residential & Social Care"], "at-home support service for adults with disabilities"),
    "4609": ("therapy", ["Rehabilitation"], "assessment and re-training unit for people with brain injury"),
}
# categetab-level refinements (keyword names kept in the register's own French)
CAT_SERVICES = {"183": "Institut Medico-Educatif (IME)", "186": "ITEP", "189": "CMPP", "190": "CAMSP", "182": "SESSAD",
                "255": "Maison d'Accueil Specialisee (MAS)", "437": "Foyer d'Accueil Medicalise (FAM)", "246": "ESAT",
                "247": "Entreprise adaptee", "382": "Foyer de Vie", "252": "Foyer d'hebergement", "446": "SAVS", "445": "SAMSAH",
                "609": "Maison Departementale des Personnes Handicapees (MDPH)"}
TYPVOIE = {"R": "Rue", "AV": "Avenue", "BD": "Boulevard", "RTE": "Route", "CHE": "Chemin", "PL": "Place", "IMP": "Impasse",
           "ALL": "Allee", "RPT": "Rond-point", "QUAI": "Quai", "CRS": "Cours", "PAS": "Passage", "SQ": "Square",
           "VOIE": "Voie", "LD": "Lieu-dit", "CITE": "Cite", "ZA": "ZA", "ZI": "ZI", "PROM": "Promenade", "CHEM": "Chemin",
           "RES": "Residence", "TSSE": "Terrasse", "VLA": "Villa", "PRV": "Parvis", "MTE": "Montee", "SEN": "Sentier"}


def fmt_phone(p):
    p = re.sub(r"\D", "", p or "")
    return " ".join(p[i:i + 2] for i in range(0, 10, 2)) if len(p) == 10 else (p or None)


ACRONYMS = {"MAS", "FAM", "IME", "IMPRO", "IMP", "SESSAD", "SSESD", "ESAT", "ITEP", "CMPP", "CAMSP", "SAVS", "SAMSAH", "CAJ",
            "FH", "MDPH", "APF", "ADAPEI", "APAJH", "UEROS", "CRA", "ARSEA", "ARSLA", "AFM", "ADMR", "EA", "EEAP", "IEM", "IES",
            "CMP", "CATTP", "ACSEA", "ASEI", "ADSEA", "AEIM", "UNAPEI", "SAJ", "FAS", "FDV", "CRP", "CPO", "SAAD", "SPASAD",
            "ESMS", "CHU", "CH", "CHS", "EPSM", "ASSAD", "AVS", "SAMSAH", "UEM", "UEMA", "ULIS", "II", "III", "IV", "SAAJ", "PCPE"}
SMALL = {"de", "du", "des", "la", "le", "les", "et", "sur", "sous", "en", "aux", "au", "a", "d", "l", "un", "une", "pour", "par"}


def titled(s):
    """FINESS names are upper-case; title-case them but keep acronyms and lower-case the small French words."""
    s = rc.clean(s)
    if not s.isupper():
        return s
    out = []
    for i, tok in enumerate(re.split(r"(\s+|-|')", s)):
        if tok in ACRONYMS:
            out.append(tok)
        elif tok.lower() in SMALL and i > 0:
            out.append(tok.lower())
        else:
            out.append(tok.capitalize())
    return "".join(out)


_tr = {}


def to_wgs(epsg, x, y):
    if epsg not in _tr:
        _tr[epsg] = Transformer.from_crs(epsg, 4326, always_xy=True)
    return _tr[epsg].transform(x, y)


def main():
    path = rc.download(URL, os.path.join(SCRATCH, "geo.csv"))
    structs, geo = {}, {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.reader(f, delimiter=";"):
            if not r:
                continue
            if r[0] == "structureet":
                structs[r[1]] = r
            elif r[0] == "geolocalisation":
                geo[r[1]] = r
    print(f"FINESS: {len(structs)} establishments, {len(geo)} geolocated")
    entries, nogeo, bad = [], 0, 0
    for fid, r in structs.items():
        cat, agg = r[18], r[20]
        if agg in AGG:
            typ, services, kind = AGG_MAP[agg]
        elif cat in EXTRA_CAT:
            typ, services = EXTRA_CAT[cat]
            kind = r[19]
        else:
            continue
        g = geo.get(fid)
        m = re.search(r"EPSG:(\d+)", g[4]) if g else None
        if not g or not m or not g[2] or not g[3]:
            nogeo += 1
            continue
        try:
            lng, lat = to_wgs(int(m.group(1)), float(g[2]), float(g[3]))
        except Exception:  # noqa: BLE001
            bad += 1
            continue
        if not rc.plausible("FR", lat, lng):
            bad += 1
            continue
        street = " ".join(x for x in (r[7], TYPVOIE.get(r[8], titled(r[8])), titled(r[9])) if x)
        addr = ", ".join(x for x in (street, titled(r[15]) if not re.match(r"^\d", r[15]) else
                                      f"{r[15][:5]} {titled(r[15][6:])}".strip()) if x)
        desc = f"{r[19]}."
        entries.append(rc.entry(titled(r[3]) or titled(r[4]), SOURCE, typ, services, desc, address=addr, phone=fmt_phone(r[16]),
                                lat=lat, lng=lng, external_id=f"finess:{fid}", scope="general"))
    print(f"kept {len(entries)}; {nogeo} without coordinates, {bad} implausible/failed projection")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_finess.json"), entries)
    rc.spot_check(out, 12, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
