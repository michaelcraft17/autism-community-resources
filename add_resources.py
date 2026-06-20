"""
Daily Autism Resource Adder
Pulls 50 new resources from free public APIs (SAMHSA + OpenStreetMap)
Zero API keys required.
"""

import json
import time
import random
import requests
import os
from pathlib import Path

JSON_FILE = "community_resources.json"
TARGET_NEW = 50

# US states to rotate through daily so we don't repeat the same area
US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"
]

# Pick 3 states based on day of year so it rotates
import datetime
day = datetime.date.today().timetuple().tm_yday
state_pool = [US_STATES[i % len(US_STATES)] for i in range(day, day + 3)]


def load_existing():
    if not Path(JSON_FILE).exists():
        return []
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_existing_names(resources):
    return {r.get("name", "").strip().lower() for r in resources}


def format_phone(raw):
    digits = "".join(c for c in str(raw or "") if c.isdigit())
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 11 and digits[0] == "1":
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return raw or ""


# ── Source 1: SAMHSA Treatment Locator API (completely free) ──────────────────
def fetch_samhsa(state: str) -> list:
    """
    SAMHSA's FHIR-based treatment locator. Returns behavioral health /
    autism-related service providers by state. No key needed.
    """
    results = []
    url = "https://findtreatment.gov/locator/api"
    params = {
        "state": state,
        "sType": "SA",   # substance + mental health (includes autism support)
        "pageSize": 30,
        "page": 1,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        facilities = data.get("facilities") or data.get("data") or []
        for f in facilities:
            name = f.get("name1") or f.get("name") or ""
            if not name:
                continue
            addr_parts = [
                f.get("street1", ""),
                f.get("city", ""),
                f.get("state", ""),
                f.get("zip", ""),
            ]
            address = ", ".join(p for p in addr_parts if p)
            phone = format_phone(f.get("phone") or f.get("phone1") or "")
            website = f.get("website") or ""
            lat = f.get("latitude") or f.get("lat") or 0
            lng = f.get("longitude") or f.get("lon") or 0
            results.append({
                "name": name.strip(),
                "address": address,
                "phone": phone,
                "website": website,
                "type": "therapy",
                "description": f"Behavioral health and support services in {f.get('city', state)}.",
                "coordinates": {"lat": float(lat), "lng": float(lng)},
            })
    except Exception as e:
        print(f"SAMHSA fetch failed for {state}: {e}")
    return results


# ── Source 2: OpenStreetMap Overpass API (free, no key) ───────────────────────
OSM_QUERIES = [
    # Autism / special needs centers
    '[out:json][timeout:30];area["ISO3166-2"~"US-{state}"][admin_level=4]->.a;'
    'node["amenity"="social_facility"]["social_facility:for"~"disabled|autism"](area.a);out body;',

    # Healthcare clinics + therapy offices
    '[out:json][timeout:30];area["ISO3166-2"~"US-{state}"][admin_level=4]->.a;'
    'node["healthcare"~"therapist|psychologist|counsellor"](area.a);out body;',
]

OSM_TYPE_MAP = {
    "therapist": "therapy",
    "psychologist": "medical",
    "counsellor": "therapy",
    "social_facility": "social",
}


def fetch_osm(state: str) -> list:
    results = []
    overpass_url = "https://overpass-api.de/api/interpreter"
    for query_template in OSM_QUERIES:
        query = query_template.replace("{state}", state)
        try:
            r = requests.post(overpass_url, data={"data": query}, timeout=35)
            r.raise_for_status()
            elements = r.json().get("elements", [])
            for el in elements:
                tags = el.get("tags", {})
                name = tags.get("name") or tags.get("operator") or ""
                if not name:
                    continue
                city = tags.get("addr:city", "")
                addr = ", ".join(filter(None, [
                    tags.get("addr:housenumber", ""),
                    tags.get("addr:street", ""),
                    city,
                    tags.get("addr:state", state),
                    tags.get("addr:postcode", ""),
                ]))
                phone = format_phone(tags.get("phone") or tags.get("contact:phone") or "")
                website = tags.get("website") or tags.get("contact:website") or ""
                lat = el.get("lat", 0)
                lng = el.get("lon", 0)
                hc = tags.get("healthcare", tags.get("social_facility", "social"))
                rtype = OSM_TYPE_MAP.get(hc, "social")
                description = tags.get("description") or f"Community support service in {city or state}."
                results.append({
                    "name": name.strip(),
                    "address": addr,
                    "phone": phone,
                    "website": website,
                    "type": rtype,
                    "description": description,
                    "coordinates": {"lat": float(lat), "lng": float(lng)},
                })
        except Exception as e:
            print(f"OSM fetch failed for {state}: {e}")
        time.sleep(1)  # be polite to Overpass
    return results


# ── Source 3: HRSA Health Center Finder (free, no key) ───────────────────────
def fetch_hrsa(state: str) -> list:
    """
    HRSA's Federally Qualified Health Centers — many serve autism/special needs.
    """
    results = []
    url = "https://findahealthcenter.hrsa.gov/api/search"
    params = {"state": state, "pageSize": 20}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = data.get("results") or data.get("data") or []
        for item in items:
            name = item.get("name") or item.get("siteName") or ""
            if not name:
                continue
            address = item.get("address") or item.get("street") or ""
            city = item.get("city") or ""
            if city and city not in address:
                address = f"{address}, {city}, {state}"
            phone = format_phone(item.get("phone") or "")
            website = item.get("webAddress") or item.get("website") or ""
            lat = item.get("latitude") or 0
            lng = item.get("longitude") or 0
            results.append({
                "name": name.strip(),
                "address": address,
                "phone": phone,
                "website": website,
                "type": "medical",
                "description": f"Federally qualified health center serving the {city or state} community.",
                "coordinates": {"lat": float(lat), "lng": float(lng)},
            })
    except Exception as e:
        print(f"HRSA fetch failed for {state}: {e}")
    return results


def is_valid(resource: dict) -> bool:
    """Filter out entries with no useful data."""
    return bool(resource.get("name")) and bool(
        resource.get("address") or resource.get("website") or resource.get("phone")
    )


def main():
    print(f"Loading existing resources from {JSON_FILE}...")
    existing = load_existing()
    known_names = get_existing_names(existing)
    print(f"  {len(existing)} existing resources, {len(known_names)} unique names")

    candidates = []
    for state in state_pool:
        print(f"\nFetching from state: {state}")
        candidates += fetch_samhsa(state)
        candidates += fetch_osm(state)
        candidates += fetch_hrsa(state)
        time.sleep(0.5)

    print(f"\nTotal candidates fetched: {len(candidates)}")

    # Deduplicate against existing and within batch
    seen_in_batch = set()
    new_resources = []
    for r in candidates:
        name_key = r["name"].strip().lower()
        if name_key in known_names or name_key in seen_in_batch:
            continue
        if not is_valid(r):
            continue
        seen_in_batch.add(name_key)
        new_resources.append(r)
        if len(new_resources) >= TARGET_NEW:
            break

    print(f"New unique resources to add: {len(new_resources)}")

    if not new_resources:
        print("Nothing new to add today — try again tomorrow (different states will be queried).")
        return

    updated = existing + new_resources
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {JSON_FILE} now has {len(updated)} resources (+{len(new_resources)} new).")


if __name__ == "__main__":
    main()
