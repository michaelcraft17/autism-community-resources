#!/usr/bin/env python3
"""
Russia, sources R3 + R5: downloads the small official files/pages tools/russia_build.py parses.
Idempotent (re-downloads each run, ~6 MB total), keyless, plain HTTPS GETs.

  minjust_opu.csv  Ministry of Justice register of NGOs providing socially useful services,
                   via the national open-data portal data.gov.ru (UTF-8-sig, ';'-separated, NO
                   header row; columns: name, OGRN, Minjust reg. no., services, 3 dates,
                   region, status). Dataset 5b8f83c2-8eac-403e-bba1-dd7a9db3e6c9.
  sonko.csv        Ministry of Labour register of federal support recipients (SONKO), 2021.
  vog.html         Russian Society of the Deaf (VOG) regional-branch page, 77 branches.
  zv_ngo.html      zhit-vmeste.ru page of ~13 all-Russian disability NGOs.

Usage: python3 tools/russia_misc_fetch.py
Writes into the gitignored tools/russia_scratch/.
"""
import os
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "russia_scratch")
os.makedirs(SCRATCH, exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0 (autism-community-resources research; contact michaelcraft17@gmail.com)"}
FILES = {
    "minjust_opu.csv": "https://data.gov.ru/portal-back/api/v1/storage?id=48273ed0-e3ce-4355-9725-30f4de3d7244",
    "sonko.csv": "https://mintrud.gov.ru/opendata/7710914971-reestr_sonko/data-20210616-structure-20210616.csv",
    "vog.html": "https://voginfo.ru/about/regionalnye-otdelenija/",
    "zv_ngo.html": "https://zhit-vmeste.ru/obshchestvennye-organizatsii-invalidov/",
}

for name, url in FILES.items():
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=180) as r:
        data = r.read()
    with open(os.path.join(SCRATCH, name), "wb") as f:
        f.write(data)
    print(f"{name}: {len(data):,} bytes")
