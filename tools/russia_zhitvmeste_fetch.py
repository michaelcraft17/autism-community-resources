#!/usr/bin/env python3
"""
Russia, source R2: the Ministry of Labour's "Dostupnaya sreda" (accessible environment) map at
https://zhit-vmeste.ru/map/ -- the largest official Russian source, with coordinates.

The map page's own jQuery call reads a GeoJSON feed:
    /map/data_new.php?sub=<regionId>&vid=1&type=<typeId>&name=&addr=&check_1=..&check_5=
Keyless plain GET. GOTCHA: geometry.coordinates is [lat, lon] (Yandex order), NOT GeoJSON's
[lon, lat]. Name and object id sit inside properties.balloonContent as
<a href='/map/?ELEMENT_ID=N'>name</a>. Without `sub` the feed only returns per-region clusters.

Types kept (the others -- education, health, sport, culture, workplaces -- are ordinary buildings
assessed for accessibility, not disability services):
    614     social protection (rehab centres, residential homes, КЦСОН, admin offices ...)
    153731  medico-social expertise (state disability-assessment bureaus)
    225775  inclusive children's recreation

Writes (gitignored scratch): tools/russia_scratch/zv.json -- one raw row per map object.
tools/russia_build.py filters/dedupes/categorises them.

Usage: python3 tools/russia_zhitvmeste_fetch.py     (~4-5 minutes at 0.2 s between requests)
"""
import html
import json
import os
import re
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "russia_scratch")
os.makedirs(SCRATCH, exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0 (autism-community-resources research; contact michaelcraft17@gmail.com)"}
TYPES = {"614": "social_protection", "153731": "mse", "225775": "inclusive_recreation"}
DELAY = 0.2


def fetch(url, tries=4):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
            last = e
    raise last


def main():
    page = fetch("https://zhit-vmeste.ru/map/")
    select = re.search(r'<select[^>]*name="sub".*?</select>', page, re.S).group(0)
    regions = [(v, html.unescape(n)) for v, n in re.findall(r'<option value="([^"]+)">([^<]+)</option>', select)]
    print(f"{len(regions)} regions")
    rows, seen = [], set()
    for rid, rname in regions:
        for tid, tname in TYPES.items():
            time.sleep(DELAY)
            url = (f"https://zhit-vmeste.ru/map/data_new.php?sub={rid}&vid=1&type={tid}"
                   "&name=&addr=&check_1=&check_2=&check_3=&check_4=&check_5=")
            try:
                data = json.loads(fetch(url))
            except Exception as e:  # noqa: BLE001
                print(f"  FAILED region {rname} type {tid}: {e}")
                continue
            for ft in data.get("features", []):
                m = re.search(r"ELEMENT_ID=(\d+)'>(.*?)</a>", ft["properties"].get("balloonContent", ""), re.S)
                if not m or (m.group(1), tid) in seen:
                    continue
                seen.add((m.group(1), tid))
                lat, lon = ft["geometry"]["coordinates"]   # Yandex order: lat first
                rows.append({"id": int(m.group(1)), "name": re.sub(r"\s+", " ", html.unescape(m.group(2))).strip(),
                             "lat": lat, "lon": lon, "region": rname, "region_id": rid, "kind": tname})
        print(f"  {rname}: {len(rows)} total so far", flush=True)
    with open(os.path.join(SCRATCH, "zv.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print(f"Wrote {len(rows)} rows")


if __name__ == "__main__":
    main()
