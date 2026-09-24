#!/usr/bin/env python3
"""
Dutch autism-related charities from the ANBI (Algemeen Nut Beogende
Instelling / "public benefit organization") register -- the Belastingdienst
(Dutch Tax Administration)'s official, weekly-refreshed, CC-0 public-domain
open dataset of every organization holding ANBI tax status in the
Netherlands:

    https://download.belastingdienst.nl/data/anbi/anbi.zip
    (documented at https://www.belastingdienst.nl/wps/wcm/connect/bldcontentnl/
     themaoverstijgend/brochures_en_publicaties/open_data_anbi)

Same tier of source as tools/france_rna_fetch.py's RNA or
tools/cqc_uk_fetch.py's CQC directory: an official government registry, not
scraped or LLM-narrated. ~55,000 total organizations; filtered here by name/
alias containing a Dutch autism-root keyword (autisme/autistisch/autistische/
autisten/autist -- deliberately NOT the bare substring "autis", which false-
matches "nautisch"/"nautische" [nautical] and "nautischfonds").

Known dataset limitation: ANBI only records organization name, alias, city
(vestigingsPlaats -- no street address), and website -- no purpose/mission
text and no street-level address, so entries here are geocoded to city
centroid via Nominatim rather than a precise street address. This registry
is also much narrower than France's RNA (ANBI is a specific tax-status
election, not "any declared association"), so the yield is a few dozen
organizations, not thousands -- expected, not a bug.

Usage:
    python3 tools/netherlands_anbi_fetch.py

Writes:
    tools/netherlands_anbi_scratch/anbi.xml       raw downloaded registry (gitignored)
    new_resources_netherlands_anbi.json            final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request
import re
import xml.etree.ElementTree as ET
import zipfile
import io

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "netherlands_anbi_scratch")
os.makedirs(SCRATCH, exist_ok=True)
XML_PATH = os.path.join(SCRATCH, "anbi.xml")
OUT_PATH = os.path.join(REPO, "new_resources_netherlands_anbi.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
ZIP_URL = "https://download.belastingdienst.nl/data/anbi/anbi.zip"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Netherlands ANBI register - official Belastingdienst (Tax Administration) open data"

KEYWORDS = ["autisme", "autistisch", "autistische", "autisten", "autist"]
EXCLUDE_SUBSTR = ["in liquidatie"]  # being wound down, not operating


def download_xml():
    if os.path.exists(XML_PATH):
        print(f"  using cached {XML_PATH}")
        return
    req = urllib.request.Request(ZIP_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml_name = next(n for n in zf.namelist() if n.endswith(".xml"))
        with zf.open(xml_name) as f, open(XML_PATH, "wb") as out:
            out.write(f.read())
    print(f"  downloaded and extracted to {XML_PATH}")


def geocode(city):
    params = {"q": f"{city}, Netherlands", "format": "json", "limit": 1}
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.loads(resp.read())
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception as e:
        print(f"  geocode failed for {city!r}: {e}")
    return None


def main():
    print("Fetching ANBI register...")
    download_xml()

    tree = ET.parse(XML_PATH)
    root = tree.getroot()

    matches = []
    for b in root.findall("beschikking"):
        naam = b.findtext("naam") or ""
        alias = b.findtext("aliasNaam") or ""
        combined = (naam + " " + alias).lower()
        if any(k in combined for k in EXCLUDE_SUBSTR):
            continue
        if any(k in combined for k in KEYWORDS):
            matches.append({
                "name": re.sub(r"\s+", " ", naam).strip().title(),
                "alias": re.sub(r"\s+", " ", alias).strip() if alias else None,
                "city": b.findtext("vestigingsPlaats"),
                "website": b.findtext("webSite"),
            })
    print(f"  {len(matches)} matches after keyword filter")

    resources = []
    for m in matches:
        coords = geocode(m["city"]) if m["city"] else None
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        description = f"Dutch ANBI-registered public benefit organization"
        if m["alias"]:
            description += f" (\"{m['alias']}\")"
        description += f", based in {m['city']}." if m["city"] else "."
        entry = {
            "name": m["name"],
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": description,
        }
        if m["city"]:
            entry["address"] = f"{m['city']}, Netherlands"
        if m["website"]:
            entry["website"] = m["website"]
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        resources.append(entry)
        print(f"  {m['name']}: {'geocoded' if coords else 'NOT geocoded (placeless)'}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} geocoded")


if __name__ == "__main__":
    main()
