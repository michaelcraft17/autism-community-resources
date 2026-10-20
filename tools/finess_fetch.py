#!/usr/bin/env python3
"""
France: disability establishments and services from FINESS, the national register of health and
social establishments (Etalab open licence), one keyless CSV with addresses AND coordinates:

    etalab-cs1100507-stock-<YYYYMMDD>-<hhmm>.csv  ('structureet' rows + 'geolocalisation' rows)
    from the data.gouv.fr dataset "finess-extraction-du-fichier-des-etablissements"

The newest such file is looked up in the dataset's resources through the data.gouv.fr API (greatest date in its
title or URL). If the lookup fails or finds no such file the run stops -- it never falls back to an older file.
`python3 tools/finess_fetch.py --url <csv url>` uses that file instead (manual runs). The file name is recorded as
rc.STATUS["input"]. Fewer than MIN_KEPT rows kept, or more than 1% of the selected rows without coordinates, also
stops the run (a wrong or cut file: the geolocalisation rows come last).

Selected by aggregate category (categagretab): 4101-4107 (education speciale / IME / ITEP / SESSAD / CMPP / CAMSP ...),
4301-4305 (adult disability: foyers, MAS, FAM, ESAT, SAVS/SAMSAH ...), 4609 (UEROS), plus MDPH (categetab 609)
and resource centres (categetab 461). CLIC (elderly), addiction and homeless services are not included.

Coordinates are projected metres -- Lambert-93 (EPSG:2154) for the mainland, the overseas departments' own
UTM/RGAF/RGR/RGFG/RGM grids -- converted with pyproj (the EPSG code is on each geolocalisation row).
Residential structures (foyers, MAS, FAM) are staffed institutions, so they are pinned at their address.
Rows are disability_scope "general". No person data in FINESS structureet rows is read.

Writes new_resources_finess.json (tools/finess_scratch/<file name> holds the raw CSV, gitignored).
"""
import argparse
import csv
import hashlib
import os
import re
import sys
import urllib.parse

from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "finess_scratch")
API = "https://www.data.gouv.fr/api/1/datasets/finess-extraction-du-fichier-des-etablissements/"
FILE_RE = re.compile(r"(?<![\w.-])etalab-cs1100507-stock-(\d{8})-[\w.-]*\.csv(?![\w.-])")
MIN_KEPT = 10000   # 14,561 kept from the 2026-05-12 file (5 selected rows had no coordinates)
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


def file_name(url):
    return urllib.parse.unquote(os.path.basename(urllib.parse.urlsplit(url).path))


def newest_stock(dataset):
    """(file name, url) of the etalab-cs1100507-stock-YYYYMMDD-*.csv resource with the greatest date in a
    data.gouv.fr dataset JSON (name taken from the URL, else the title), or None."""
    best = None
    resources = dataset.get("resources") if isinstance(dataset, dict) else None
    for res in resources if isinstance(resources, list) else []:
        if not isinstance(res, dict):
            continue
        url = res.get("url")
        if not isinstance(url, str) or not re.match(r"https?://", url):
            continue
        m = FILE_RE.search(file_name(url)) or FILE_RE.search(str(res.get("title") or ""))
        if not m:
            continue
        key = (m.group(1), str(res.get("last_modified") or ""), m.group(0))
        if best is None or key > best[0]:
            best = (key, m.group(0), url)
    return best[1:] if best else None


def discover():
    try:
        dataset = rc.get_json(API, timeout=60)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"FINESS: could not read the data.gouv.fr dataset {API} ({e!r}) -- not falling back to an older file")
    found = newest_stock(dataset)
    if not found:
        sys.exit(f"FINESS: no etalab-cs1100507-stock-YYYYMMDD-*.csv resource in {API} -- not falling back to an older file")
    return found


def cache_path(name, url):
    """Scratch copy named after the registry file, so a newer file never reuses an older download."""
    if FILE_RE.fullmatch(name):
        return os.path.join(SCRATCH, name)
    return os.path.join(SCRATCH, "url-" + hashlib.sha1(url.encode()).hexdigest()[:16] + ".csv")


def main():
    ap = argparse.ArgumentParser(description="France FINESS disability establishments -> new_resources_finess.json")
    ap.add_argument("--url", help="use this stock CSV instead of the newest one listed on data.gouv.fr")
    args = ap.parse_args()
    if args.url:
        url = args.url
        m = FILE_RE.search(file_name(url))
        name = m.group(0) if m else (file_name(url) or url)
    else:
        name, url = discover()
    print(f"FINESS: using {name} ({url})")
    rc.STATUS["input"] = f"FINESS {name}"
    path = rc.download(url, cache_path(name, url))
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
    if len(entries) < MIN_KEPT:
        sys.exit(f"FINESS {name}: only {len(entries)} rows kept (expected >= {MIN_KEPT}) -- wrong or cut file, nothing written")
    if nogeo * 100 > len(entries) + nogeo + bad:   # geolocalisation rows come last: a cut file loses them
        sys.exit(f"FINESS {name}: {nogeo} selected rows have no coordinates (5 in the 2026-05-12 file) -- probably a cut file, nothing written")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_finess.json"), entries)
    rc.spot_check(out, 12, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
