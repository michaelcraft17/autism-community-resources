#!/usr/bin/env python3
"""
Spain has no single national association registry (interior.gob.es 403s).
Use the regional open-data registries instead. This script covers the 4
straightforward ones from the 2026-09-25 research note
(~/Desktop/autism-registry-sources-2026-09-25.md): Catalonia (Socrata),
Basque Country (flat JSON), Madrid (CKAN CSV), Canarias (CKAN CSV).

Galicia (broken TLS intermediate chain) and Aragon (custom paginated
BRSCGI API) are NOT covered here -- left as a documented follow-up, see
HANDOFF.md, rather than disabling TLS verification or reverse-engineering
the paged API under this pass's time budget.

Matches both autism terms and the general-disability category fields
listed in the note's section 6a, tagging disability_scope so the general-
disability hits stay a separate, filterable layer from the autism core.

False positives guarded against (section 4 of the note):
- "BAUTISTA" (contains "autis") -- excluded via a word-boundary regex,
  same fix already used elsewhere in this pipeline for Latvia's
  "starptautisks".

Usage:
    curl -sL -o /tmp/madrid.csv "<madrid CSV url from the note>"
    curl -sL -o /tmp/canarias.csv "<canarias CSV url from the note>"
    python3 tools/spain_regional_fetch.py
"""
import csv
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "autism-community-resources research (contact: changcheng875@gmail.com)"}

AUTISM_RE = re.compile(r"(?<![a-záéíóúñ])autis", re.IGNORECASE)
ASPERGER_RE = re.compile(r"asperger", re.IGNORECASE)


def is_autism_match(*texts):
    joined = " ".join(t for t in texts if t)
    return bool(AUTISM_RE.search(joined) or ASPERGER_RE.search(joined))


def geocode(query, countrycode="es"):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "limit": 1, "countrycodes": countrycode}
    )
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
        if data:
            return {"lat": float(data[0]["lat"]), "lng": float(data[0]["lon"])}
    except Exception:
        pass
    return None


def fetch_catalonia():
    url = ("https://analisi.transparenciacatalunya.cat/resource/y6fz-g3ff.json"
           "?$where=" + urllib.parse.quote("upper(nom_entitat) like '%AUTIS%' OR upper(contingut_finalitats) like '%AUTIS%' OR upper(classificacio_especifica) like '%DISCAPACIT%'")
           + "&$limit=1000")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)
    out = []
    for row in rows:
        name = row.get("nom_entitat", "")
        purpose = row.get("contingut_finalitats", "") or ""
        classif = (row.get("classificacio_general", "") or "") + " " + (row.get("classificacio_especifica", "") or "")
        if not is_autism_match(name, purpose) and "discapacit" not in classif.lower():
            continue
        scope = "autism" if is_autism_match(name, purpose) else "general"
        addr = row.get("adreca", "")
        city = row.get("nom_poblacio", "")
        province = row.get("nom_provincia", "")
        postcode = row.get("codi_postal", "")
        full_addr = ", ".join(p for p in [addr, city, postcode, province, "Spain"] if p)
        website = row.get("pagina_web", "")
        if website and not website.startswith("http"):
            website = "https://" + website
        entry = {
            "name": name.strip(),
            "address": full_addr,
            "phone": (row.get("telefon", "") or "").split("/")[0].strip(),
            "website": website,
            "type": "general_support",
            "source": "Catalonia Registre d'Associacions (Generalitat de Catalunya)",
            "services": [],
            "description": purpose[:500] if purpose else classif.strip(),
            "coordinates": None,
            "suggested": {},
            "entity_type": "organization",
            "_geo_query": full_addr,
        }
        if scope != "autism":
            entry["disability_scope"] = scope
        out.append(entry)
    return out


def fetch_basque():
    url = "https://opendata.euskadi.eus/contenidos/ds_registros/asociaciones_euskadi/opendata/asociaciones.json"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        rows = json.load(r)
    out = []
    for row in rows:
        name = row.get("recName", "")
        goal = row.get("recGoal", "")
        goal_type = row.get("asoGoalType", "") or ""
        is_disability_type = "minusval" in goal_type.lower() or "disminu" in goal_type.lower()
        if not is_autism_match(name, goal) and not is_disability_type:
            continue
        scope = "autism" if is_autism_match(name, goal) else "general"
        lat, lon = row.get("latwgs84"), row.get("lonwgs84")
        coords = None
        try:
            if lat and lon:
                coords = {"lat": float(lat), "lng": float(lon)}
        except ValueError:
            pass
        addr = row.get("address", "")
        city = row.get("municipality", "")
        postcode = row.get("postalcode", "")
        full_addr = ", ".join(p for p in [addr, city, postcode, "Spain"] if p)
        website = row.get("webpage", "") or row.get("friendlyUrl", "")
        entry = {
            "name": name.strip(),
            "address": full_addr,
            "phone": row.get("phone", ""),
            "website": website,
            "type": "general_support",
            "source": "Basque Country Registro de Asociaciones (Gobierno Vasco)",
            "services": [],
            "description": goal[:500] if goal else goal_type,
            "coordinates": coords,
            "placeless": coords is None,
            "suggested": {},
            "entity_type": "organization",
            "_geo_query": full_addr if not coords else None,
        }
        if scope != "autism":
            entry["disability_scope"] = scope
        out.append(entry)
    return out


def fetch_madrid(csv_path="/tmp/madrid.csv"):
    out = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            name = row.get("asociación_nombre", "") or row.get("asociacion_nombre", "")
            activity = row.get("clasificacion_activdad_desc", "") or row.get("clasificacion_actividad_desc", "") or ""
            if not is_autism_match(name) and "discapacid" not in activity.lower():
                continue
            scope = "autism" if is_autism_match(name) else "general"
            addr = row.get("asociación_direccion", "") or row.get("asociacion_direccion", "")
            entry = {
                "name": (name or "").strip(),
                "address": addr.strip() if addr else "",
                "phone": "",
                "website": "",
                "type": "general_support",
                "source": "Madrid Registro de Asociaciones (Comunidad de Madrid)",
                "services": [],
                "description": activity.strip(),
                "coordinates": None,
                "suggested": {},
                "entity_type": "organization",
                "_geo_query": addr.strip() + ", Spain" if addr else None,
            }
            if scope != "autism":
                entry["disability_scope"] = scope
            out.append(entry)
    return out


def fetch_canarias(csv_path="/tmp/canarias.csv"):
    out = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            name = row.get("denominacion", "")
            activities = row.get("actividades", "") or ""
            if not is_autism_match(name, activities) and "deficiencia" not in activities.lower():
                continue
            scope = "autism" if is_autism_match(name, activities) else "general"
            street = row.get("direccion_nombre_via", "") or ""
            muni = row.get("direccion_municipio_nombre", "") or ""
            island = row.get("direccion_isla_nombre", "") or ""
            postcode = row.get("direccion_codigo_postal", "") or ""
            full_addr = ", ".join(p for p in [street, muni, island, postcode, "Spain"] if p and p != "_U")
            phone = row.get("teléfono", "") or ""
            website = row.get("dominio_internet", "") or ""
            if website == "_U":
                website = ""
            if website and not website.startswith("http"):
                website = "https://" + website
            entry = {
                "name": name.strip(),
                "address": full_addr,
                "phone": phone if phone != "_U" else "",
                "website": website,
                "type": "general_support",
                "source": "Canarias Registro de Asociaciones (Gobierno de Canarias)",
                "services": [],
                "description": activities.strip(),
                "coordinates": None,
                "suggested": {},
                "entity_type": "organization",
                "_geo_query": full_addr,
            }
            if scope != "autism":
                entry["disability_scope"] = scope
            out.append(entry)
    return out


def main():
    all_entries = []
    print("Fetching Catalonia...")
    cat = fetch_catalonia()
    print(f"  {len(cat)} matches")
    all_entries += cat

    print("Fetching Basque Country...")
    basq = fetch_basque()
    print(f"  {len(basq)} matches")
    all_entries += basq

    if os.path.exists("/tmp/madrid.csv"):
        print("Fetching Madrid...")
        mad = fetch_madrid()
        print(f"  {len(mad)} matches")
        all_entries += mad
    else:
        print("Skipping Madrid (no /tmp/madrid.csv)")

    if os.path.exists("/tmp/canarias.csv"):
        print("Fetching Canarias...")
        can = fetch_canarias()
        print(f"  {len(can)} matches")
        all_entries += can
    else:
        print("Skipping Canarias (no /tmp/canarias.csv)")

    print(f"Total pre-geocode: {len(all_entries)}")

    cache = {}
    for i, e in enumerate(all_entries):
        q = e.pop("_geo_query", None)
        if not q:
            continue
        if q not in cache:
            cache[q] = geocode(q)
            time.sleep(1.05)
        coords = cache[q]
        if coords:
            e["coordinates"] = coords
            e["placeless"] = False
        else:
            e["placeless"] = True
        if i % 20 == 0:
            print(f"  geocoded {i}/{len(all_entries)}")

    with open(os.path.join(REPO, "new_resources_spain_regional.json"), "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(all_entries)} entries to new_resources_spain_regional.json")


if __name__ == "__main__":
    main()
