#!/usr/bin/env python3
"""
Pull UK autism/learning-disability care providers from the CQC (Care Quality
Commission) care directory -- the UK government's official, structured register
of every regulated care location in England. Free, no auth, Open Government
Licence, updated weekly.

Unlike the GPT-Researcher approach, this is not an LLM describing what it thinks
exists -- every row is a real regulated provider CQC itself has on file, with a
real postcode. Only the description text below is written by hand/Claude; the
name, address, website, and service type all come straight from the CSV.

Usage:
    python3 tools/cqc_uk_fetch.py

Writes:
    tools/cqc_scratch/cqc_directory.csv       raw download (gitignored)
    tools/cqc_scratch/cqc_autism_filtered.json  filtered + geocoded rows (gitignored)
    new_resources_uk_cqc.json                  final resource-schema output (repo root)
"""
import csv
import json
import os
import re
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "cqc_scratch")
os.makedirs(SCRATCH, exist_ok=True)

CSV_PATH = os.path.join(SCRATCH, "cqc_directory.csv")
FILTERED_PATH = os.path.join(SCRATCH, "cqc_autism_filtered.json")
OUT_PATH = os.path.join(REPO, "new_resources_uk_cqc.json")

CQC_INDEX_URL = "https://www.cqc.org.uk/about-us/transparency/using-cqc-data"
HEADERS = {"User-Agent": "autism-community-resources-research/1.0"}


def find_latest_csv_url():
    """The CSV filename is dated, so scrape the index page for the current link
    rather than hardcoding a date that will go stale."""
    req = urllib.request.Request(CQC_INDEX_URL, headers=HEADERS)
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    m = re.search(r'https://www\.cqc\.org\.uk/system/files/[^"\']+_CQC_directory\.csv', html)
    if not m:
        raise RuntimeError("Couldn't find the CQC directory CSV link on the index page -- check it manually: " + CQC_INDEX_URL)
    return m.group(0)


def download_csv():
    if os.path.exists(CSV_PATH) and os.path.getsize(CSV_PATH) > 1_000_000:
        print(f"Using cached {CSV_PATH}")
        return
    url = find_latest_csv_url()
    print(f"Downloading {url} ...")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp, open(CSV_PATH, "wb") as f:
        f.write(resp.read())
    print(f"Saved {os.path.getsize(CSV_PATH)} bytes to {CSV_PATH}")


def filter_rows():
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        for _ in range(4):
            next(f)  # CQC prepends 4 metadata lines before the real header
        reader = csv.DictReader(f)
        matches = []
        for row in reader:
            blob = " ".join((v or "") for v in row.values())
            if "autis" in blob.lower():
                matches.append(row)
    print(f"Filtered {len(matches)} rows mentioning autism anywhere in the record.")
    return matches


def geocode_postcodes(rows):
    """postcodes.io: free, no key, UK-only, bulk endpoint takes up to 100 at a time."""
    postcodes = list({(r.get("Postcode") or "").strip() for r in rows if r.get("Postcode", "").strip()})
    coords = {}
    for i in range(0, len(postcodes), 100):
        batch = postcodes[i:i + 100]
        payload = json.dumps({"postcodes": batch}).encode()
        req = urllib.request.Request(
            "https://api.postcodes.io/postcodes",
            data=payload,
            headers={**HEADERS, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception as e:
            print(f"  geocode batch {i} failed: {e}")
            continue
        for item in resp.get("result", []):
            pc = item.get("query")
            res = item.get("result")
            if res:
                coords[pc] = (res["latitude"], res["longitude"], res.get("region", ""))
        time.sleep(0.2)
    print(f"Geocoded {len(coords)}/{len(postcodes)} postcodes.")
    return coords


TYPE_MAP = {
    "Residential homes": "general_support",
    "Supported living": "general_support",
    "Homecare agencies": "general_support",
    "Community services - Learning disabilities": "general_support",
    "Community services - Mental Health": "general_support",
    "Education disability services": "education",
}


def to_resource(row, coords):
    postcode = (row.get("Postcode") or "").strip()
    lat_lng = coords.get(postcode)
    types = [t.strip() for t in (row.get("Service types") or "").split("|") if t.strip()]
    mapped_types = {TYPE_MAP[t] for t in types if t in TYPE_MAP}
    rtype = "education" if "education" in mapped_types else ("general_support" if mapped_types else "general_support")

    name = (row.get("Name") or "").strip()
    website = (row.get("Service's website (if available)") or "").strip()
    phone = (row.get("Phone number") or "").strip()
    # CQC's own CSV export drops the leading 0 from UK numbers (Excel numeric-coercion artifact) --
    # restore it so these aren't unusable/miskeyed phone numbers.
    if phone.isdigit() and not phone.startswith("0"):
        phone = "0" + phone
    entry = {
        "name": name,
        "phone": phone,
        "address": f"{row.get('Address','').strip()}, {postcode}".strip(", "),
        "type": rtype,
        "source": "CQC (UK Care Quality Commission) official register, 2026",
        "services": types[:4] if types else ["Care Services"],
        "description": f"CQC-regulated {', '.join(types).lower() or 'care service'} in {row.get('Region','the UK').strip()}, operated by {row.get('Provider name','').strip()}.",
    }
    if website:
        entry["website"] = website
    if lat_lng:
        entry["coordinates"] = {"lat": lat_lng[0], "lng": lat_lng[1]}
    else:
        entry["placeless"] = True
    return entry


def main():
    download_csv()
    rows = filter_rows()
    with open(FILTERED_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    coords = geocode_postcodes(rows)
    resources = [to_resource(r, coords) for r in rows]
    # de-dupe by (name, address) -- CQC lists some providers' multiple locations separately, which is correct,
    # but a handful of rows are literally identical
    seen = set()
    deduped = []
    for r in resources:
        key = (r["name"], r.get("address", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(deduped)} entries to {OUT_PATH}")


if __name__ == "__main__":
    main()
