#!/usr/bin/env python3
"""
UK charity regulators (a different registry type from the CQC care-facility
data already in this repo -- CQC licenses care providers, these register
charitable status). Covers England & Wales (Charity Commission, CCEW) and
Northern Ireland (CCNI). Scotland (OSCR) was NOT completed in this pass --
its download link is behind a JS-driven page and a quick Playwright
discovery pass didn't surface the direct file URL in the time available;
documented as a follow-up in HANDOFF.md rather than guessed at.

CCEW ships the FULL charity register (~470K rows including removed
charities) as a single TSV, tab-separated, no address geocoding needed at
build time since it ships full postal addresses -- geocode by postcode.
CCNI's CSV comes from its own search-export endpoint.

Postcode geocoding uses postcodes.io (free, keyless, UK-specific, bulk
endpoint, much faster/friendlier than hitting Nominatim per row for a UK
postcode lookup) rather than Nominatim, to avoid adding UK-scale load to
the shared Nominatim rate-limit budget this pipeline already uses for
every other country's fetchers.

Usage:
    curl -o /tmp/ccew.zip https://ccewuksprdoneregsadata1.blob.core.windows.net/data/txt/publicextract.charity.zip
    unzip /tmp/ccew.zip -d /tmp/ccew_data
    curl -o /tmp/ccni.csv "https://www.charitycommissionni.org.uk/api/charity-search/exportSearchResultsToCsv/?homePageId=c0884e5e-b621-4563-a378-2b313e15c74a&pageNumber=1&sortOption=Rank%3Basc&searchText="
    python3 tools/uk_charity_regulators_fetch.py
"""
import csv
import json
import os
import re
import sys
import urllib.request

csv.field_size_limit(sys.maxsize)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "autism-community-resources research (contact: changcheng875@gmail.com)"}

AUTISM_RE = re.compile(r"(?<![a-z])autis", re.IGNORECASE)
ASPERGER_RE = re.compile(r"asperger", re.IGNORECASE)


def is_autism_match(*texts):
    joined = " ".join(t for t in texts if t)
    return bool(AUTISM_RE.search(joined) or ASPERGER_RE.search(joined))


def postcode_lookup_bulk(postcodes):
    """postcodes.io bulk lookup, 100 per request, free & keyless."""
    result = {}
    postcodes = [p for p in postcodes if p]
    for i in range(0, len(postcodes), 100):
        batch = postcodes[i:i + 100]
        payload = json.dumps({"postcodes": batch}).encode()
        req = urllib.request.Request(
            "https://api.postcodes.io/postcodes", data=payload,
            headers={**UA, "Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
            for item in data.get("result", []):
                if item.get("result"):
                    q = item["query"]
                    result[q] = {"lat": item["result"]["latitude"], "lng": item["result"]["longitude"]}
        except Exception as e:
            print(f"  postcode batch failed: {e}")
    return result


def fetch_ccew(path="/tmp/ccew_data/publicextract.charity.txt"):
    out = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            name = row.get("charity_name", "") or ""
            activities = row.get("charity_activities", "") or ""
            if not is_autism_match(name, activities):
                continue
            if row.get("charity_registration_status") != "Registered":
                continue  # skip removed/deregistered charities
            addr_parts = [row.get(f"charity_contact_address{i}", "") for i in range(1, 6)]
            postcode = row.get("charity_contact_postcode", "") or ""
            full_addr = ", ".join(p for p in addr_parts if p) + ((" " + postcode) if postcode else "")
            website = row.get("charity_contact_web", "") or ""
            if website and not website.startswith("http"):
                website = "https://" + website
            entry = {
                "name": name.strip(),
                "address": full_addr.strip(", ").strip(),
                "phone": row.get("charity_contact_phone", "") or "",
                "website": website,
                "type": "general_support",
                "source": "England & Wales Charity Commission (registered charity)",
                "services": [],
                "description": activities[:500].strip(),
                "coordinates": None,
                "suggested": {},
                "entity_type": "organization",
                "_postcode": postcode.strip(),
            }
            out.append(entry)
    return out


def fetch_ccni(path="/tmp/ccni.csv"):
    out = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Charity name", "") or ""
            does = row.get("What the charity does", "") or ""
            helps = row.get("Who the charity helps", "") or ""
            if not is_autism_match(name, does, helps):
                continue
            website = row.get("Website", "") or ""
            if website and not website.startswith("http"):
                website = "https://" + website
            addr = row.get("Public address", "") or ""
            entry = {
                "name": name.strip(),
                "address": addr.strip(),
                "phone": row.get("Telephone", "") or "",
                "website": website,
                "type": "general_support",
                "source": "Northern Ireland Charity Commission (CCNI)",
                "services": [],
                "description": (does + " " + helps)[:500].strip(),
                "coordinates": None,
                "placeless": True,
                "suggested": {},
                "entity_type": "organization",
            }
            out.append(entry)
    return out


def main():
    all_entries = []
    if os.path.exists("/tmp/ccew_data/publicextract.charity.txt"):
        ccew = fetch_ccew()
        print(f"CCEW: {len(ccew)} matches")
        all_entries += ccew
    else:
        print("Skipping CCEW (file not found)")

    if os.path.exists("/tmp/ccni.csv"):
        ccni = fetch_ccni()
        print(f"CCNI: {len(ccni)} matches")
        all_entries += ccni
    else:
        print("Skipping CCNI (file not found)")

    postcodes = list({e["_postcode"] for e in all_entries if e.get("_postcode")})
    print(f"Looking up {len(postcodes)} unique postcodes...")
    coords_map = postcode_lookup_bulk(postcodes)

    for e in all_entries:
        pc = e.pop("_postcode", None)
        if pc and pc in coords_map:
            e["coordinates"] = coords_map[pc]
            e["placeless"] = False
        elif "coordinates" not in e or e["coordinates"] is None:
            e["coordinates"] = None
            e["placeless"] = True

    with open(os.path.join(REPO, "new_resources_uk_charity_regulators.json"), "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(all_entries)} entries to new_resources_uk_charity_regulators.json")


if __name__ == "__main__":
    main()
