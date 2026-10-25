#!/usr/bin/env python3
"""
Austria, two small open-data additions to austria_fetch.py (shard AT):
  AT6  Tirol "Daseinsvorsorge" POI layer (WFS on data.gv.at, CC BY 4.0), OBJEKT = DPSCH3 "Pflichtschule - Sonderschule"
       (20 rows, own coordinates + street). A school is kept only if no Statistik Austria special school (the at-skz rows
       built by austria_fetch.py from tools/austria_scratch/schulen.json) lies within 1 km; 19 of the 20 are already there
       and one (Imst, Auf Arzill 151) is not, because Statistik files that building as a Volksschule.
  AT7  Vienna open data BERATUNGSZENTROGD: only the Fonds Soziales Wien "Beratungszentrum Behindertenhilfe" (1 of 6 centres;
       the others are care, homelessness and residential-home counselling). The centre's e-mail and fax are not kept.
Core. Nothing here is a group home or a person. Output: new_resources_austria_extra.json
"""
import json
import math
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402
import austria_fetch as af  # noqa: E402  (special-school filter, same scratch inputs)

TIROL = ("https://dservices3.arcgis.com/hG7UfxX49PQ8XkXh/arcgis/services/Daseinsvorsorge/WFSServer?service=WFS&version=2.0.0"
         "&request=GetFeature&typeNames=Daseinsvorsorge:Daseinsvorsorge&outputFormat=GEOJSON")
TIROL_FILTER = ('<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0"><fes:PropertyIsEqualTo><fes:ValueReference>OBJEKT'
                '</fes:ValueReference><fes:Literal>DPSCH3</fes:Literal></fes:PropertyIsEqualTo></fes:Filter>')
WIEN = ("https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0&typeName=ogdwien:BERATUNGSZENTROGD"
        "&srsName=EPSG:4326&outputFormat=json")
SRC_TIROL = "Austria Tirol Daseinsvorsorge open data (special schools)"
SRC_WIEN = "Austria Vienna open data counselling centres (Behindertenhilfe)"


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.2, (a[1] - b[1]) * 111.2 * math.cos(math.radians(a[0])))


def statistik_special():
    """(lat, lng) of the special schools austria_fetch.py builds, and a municipality name for any school point."""
    path = rc.download(af.FILES["schulen.json"], os.path.join(af.SCRATCH, "schulen.json"))
    feats = json.load(open(path))["features"]
    special, allpts = [], []
    for f in feats:
        p, typ = f["properties"], f["properties"]["TYP"]
        lng, lat = f["geometry"]["coordinates"]
        allpts.append((lat, lng, p["GEMNAME"]))
        name = af.tidy(p["BEZEICHNUNG"])
        if typ in af.NOT_SPECIAL_TYPE or re.search(r"sozialbetreuung|krankenpflege", name, re.I):
            continue
        if typ == "SS" or af.SPECIAL.search(name):
            special.append((lat, lng))
    return special, allpts


def main():
    rc.STATUS["input"] = "Tirol Daseinsvorsorge WFS (DPSCH3), Vienna BERATUNGSZENTROGD, Statistik Austria schools"
    special, allpts = statistik_special()
    out, kept, dup = [], 0, 0

    d = rc.get_json(TIROL + "&filter=" + urllib.parse.quote(TIROL_FILTER), delay=1.0)
    for f in d["features"]:
        p = f["properties"]
        if p.get("OBJEKTBEZEICHNUNG") != "Pflichtschule - Sonderschule" or not f.get("geometry"):
            continue
        lng, lat = f["geometry"]["coordinates"][:2]
        if not rc.plausible("AT", lat, lng):
            continue
        if any(km((lat, lng), s) <= 1.0 for s in special):
            dup += 1
            continue
        near = min(allpts, key=lambda a: km((lat, lng), a[:2]))
        gem = near[2] if km((lat, lng), near[:2]) <= 3 else "Tirol"
        name = af.tidy(p["NAME"]).replace('\\"', '"')
        if name.lower() == "allgemeine sonderschule":
            name = f"Allgemeine Sonderschule {gem}"
        out.append(rc.entry(name, SRC_TIROL, "education", ["Special education", "Education"],
                            f"Special school (Sonderschule) in {gem}, Tirol, from the Land Tirol Daseinsvorsorge layer (status {af.tidy(p.get('STAND'))}).",
                            address=f"{af.tidy(p['STR'])}, {gem}, Österreich", lat=lat, lng=lng,
                            external_id=f"at-tirol-ds:{p['OBJECTID']}", scope="general"))
        kept += 1

    nw = 0
    for f in rc.get_json(WIEN, delay=1.0)["features"]:
        p = f["properties"]
        if "behindertenhilfe" not in (p.get("BEZEICHNUNG") or "").lower() or not f.get("geometry"):
            continue
        lng, lat = f["geometry"]["coordinates"][:2]
        if not rc.plausible("AT", lat, lng):
            continue
        street = re.sub(r",?\s*(Erdgeschoß|Erdgeschoss|\d+\.\s*Stock|Stiege.*)$", "", af.tidy(p["ADRESSE"]))
        plz = f"1{int(p['BEZIRK']):02d}0"
        out.append(rc.entry("Beratungszentrum Behindertenhilfe (Fonds Soziales Wien)", SRC_WIEN, "social", ["Information & Support"],
                            "Fonds Soziales Wien counselling centre for the Vienna disability services (Behindertenhilfe): advice on benefits, "
                            "help with applications and assessment. Responsible for all of Vienna.",
                            address=f"{street}, {plz} Wien, Österreich", phone=af.tidy(p.get("TELEFON")) or None, website=af.web(p.get("WEBLINK1")),
                            lat=lat, lng=lng, external_id=f"at-wien-bz:{p['OBJECTID']}", scope="general"))
        nw += 1

    print(f"Tirol special schools kept {kept} (+{dup} already within 1 km of a Statistik Austria special school); Vienna Behindertenhilfe {nw}")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_austria_extra.json"), out)
    for e in fin:
        print("  ", e["external_id"], e["name"], "|", e["address"], "|", e.get("phone"), e["coordinates"])


if __name__ == "__main__":
    main()
