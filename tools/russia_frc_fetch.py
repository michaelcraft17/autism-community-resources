#!/usr/bin/env python3
"""
Russia, source R1: the Federal Resource Centre for children with ASD's national navigator of
organisations that help children with autism (https://autism-frc.ru/companies). The centre sits at
Moscow State University of Psychology & Education under the Ministry of Education, so every listed
organisation is autism-relevant by definition.

Free, keyless, plain server-rendered HTML. One unfiltered page holds every company block
(<section class='company' data-id=N>: name, phone, email, website, sometimes a street address).
Region, type and sector are NOT in those blocks; they are only attached by the page's own GET
filters, so this fetches ~95 filtered pages (region / type / sector) and joins them on data-id.

Writes (gitignored scratch): tools/russia_scratch/frc.json  -- raw parsed records.
tools/russia_build.py turns them into resource-schema entries (geocoding, categories, dedupe).

Usage: python3 tools/russia_frc_fetch.py      (about 1-2 minutes, 0.4 s between requests)
"""
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "russia_scratch")
os.makedirs(SCRATCH, exist_ok=True)
BASE = "https://autism-frc.ru/companies"
HEADERS = {"User-Agent": "Mozilla/5.0 (autism-community-resources research; contact michaelcraft17@gmail.com)"}
DELAY = 0.4

TYPES = {1: "state", 2: "ngo", 3: "charitable_foundation", 4: "commercial"}
SECTORS = {1: "education", 2: "health", 3: "social_protection", 4: "culture", 5: "sport"}


def get(params=None):
    url = BASE + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 -- retry on any network hiccup
            time.sleep(2 * (attempt + 1))
            last = e
    raise last


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


SECTION_RE = re.compile(r"<section class='company' data-id='(\d+)'>(.*?)</section>", re.S)


def parse_companies(page):
    out = {}
    for cid, body in SECTION_RE.findall(page):
        name = clean(re.search(r"<h4 class='title'>(.*?)</h4>", body, re.S).group(1))
        addr = re.search(r"<div class='col-md-4-6'>(.*?)</div>", body, re.S)
        phone = re.search(r"<div class='phone'>(.*?)</div>", body, re.S)
        site = re.search(r"<div class='site'>\s*<a href='([^']*)'", body, re.S)
        phone_txt = clean(phone.group(1)) if phone else ""
        phone_txt = re.sub(r"^Тел\.?:?\s*", "", phone_txt)
        out[int(cid)] = {
            "id": int(cid), "name": name,
            "address": clean(addr.group(1)) if addr else "",
            "phone": phone_txt,
            "website": (site.group(1).strip() if site else ""),
        }
    return out


def main():
    full_page = get()
    records = parse_companies(full_page)
    print(f"Unfiltered page: {len(records)} companies")

    regions = re.findall(r'<option value="(\d+)">([^<]+)</option>',
                         re.search(r'id="company_region_id">(.*?)</select>', full_page, re.S).group(1))
    print(f"{len(regions)} regions")
    for rid, rname in regions:
        time.sleep(DELAY)
        for cid in parse_companies(get({"company[region_id]": rid})):
            if cid in records:
                records[cid]["region"] = html.unescape(rname)
    for tid, tname in TYPES.items():
        time.sleep(DELAY)
        for cid in parse_companies(get({"company[companytype_id]": tid})):
            if cid in records:
                records[cid]["org_type"] = tname
    for sid, sname in SECTORS.items():
        time.sleep(DELAY)
        for cid in parse_companies(get({"company[department_id]": sid})):
            if cid in records:
                records[cid]["sector"] = sname

    rows = sorted(records.values(), key=lambda r: r["id"])
    with open(os.path.join(SCRATCH, "frc.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(f"{len(rows)} records; with region {sum(1 for r in rows if r.get('region'))}, "
          f"address {sum(1 for r in rows if r['address'])}, website {sum(1 for r in rows if r['website'])}, "
          f"phone {sum(1 for r in rows if r['phone'])}")


if __name__ == "__main__":
    main()
