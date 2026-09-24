#!/usr/bin/env python3
"""
Ukrainian autism-related organizations from the Unified State Register
of Legal Entities, Individual Entrepreneurs, and Public Formations
(Єдиний державний реєстр юридичних осіб, фізичних осіб-підприємців та
громадських формувань), published as a full official bulk export on
Ukraine's national open-data portal:

    https://data.gov.ua/dataset/1c7f3815-3259-45e0-bdf1-64d3f2e64a4c
    (dataset id used here: a1799820-195b-4982-8141-6e84f58103e7)

Free, no API key, CC-licensed. This is the single largest bulk source
this project has ever processed: the "UO" (legal entities) resource
alone is a ~319MB zip containing one ~3.2GB windows-1251-encoded XML
file covering every legal entity in Ukraine. Streamed and filtered
record-by-record rather than loaded into memory (which would not fit)
or parsed with a DOM-based XML library (which would).

Known gotcha, found the hard way: naive byte-level `bytes.lower()`
keyword matching does NOT correctly case-fold multi-byte UTF-8
Cyrillic text (it only folds ASCII A-Z), so searching for the
lowercase keyword against text still containing uppercase Cyrillic
names silently missed all but one match on the first attempt. Fixed
by decoding each record to a Python `str` before `.lower()`, which
does proper Unicode case folding.

No address field exists anywhere in this dataset at all (plausibly a
deliberate wartime omission from the public export, not a data gap
specific to this project). A handful of organizations name a city or
oblast in their own registered name (e.g. "АУТИЗМ-ЖИТОМИР",
"ТЕРНОПІЛЬСЬКИЙ ОБЛАСНИЙ...") -- those are geocoded to that place;
everything else is placeless (country-level).

Genuinely the deepest single addition of this "single-listing
countries" round: 41 active organizations found (2 excluded: one
"припинено" / terminated, one "в стані припинення" / in the process of
being terminated).

Usage:
    python3 tools/ukraine_edr_fetch.py
    (downloads ~319MB the first run; cached afterward. The full
    decode+scan pass takes several minutes -- it streams ~3.2GB.)

Writes:
    tools/ukraine_edr_scratch/UO.zip   raw downloaded bulk export (gitignored)
    new_resources_ukraine.json          final resource-schema output (repo root)
"""
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "ukraine_edr_scratch")
os.makedirs(SCRATCH, exist_ok=True)
ZIP_PATH = os.path.join(SCRATCH, "UO.zip")
OUT_PATH = os.path.join(REPO, "new_resources_ukraine.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
ZIP_URL = ("https://data.gov.ua/dataset/03cc1239-3988-4451-aa0d-aadb77448714/"
           "resource/d40cc921-39bb-44fd-be06-dc02589f45c6/download/uo.zip")
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = ("Ukraine Unified State Register of Legal Entities, Individual Entrepreneurs, "
          "and Public Formations - official open data")

KEYWORD = "аутизм"
EXCLUDE_STAN_SUBSTR = ["припинено", "припинення"]  # terminated / being terminated

# Ukrainian place names to try extracting from an org's own name for a coarse geocode.
KNOWN_PLACES = [
    "Тернопільський", "Запорізька", "Житомир", "Дніпро", "Харківськ",
    "Київ", "Львів", "Одес", "Донецьк", "Чернігів", "Полтав", "Закарпатт",
]
PLACE_TO_CITY = {
    "Тернопільський": "Ternopil", "Запорізька": "Zaporizhzhia", "Житомир": "Zhytomyr",
    "Дніпро": "Dnipro", "Харківськ": "Kharkiv", "Київ": "Kyiv", "Львів": "Lviv",
    "Одес": "Odesa", "Донецьк": "Donetsk", "Чернігів": "Chernihiv",
    "Полтав": "Poltava", "Закарпатт": "Zakarpattia Oblast",
}


def download_zip():
    if os.path.exists(ZIP_PATH):
        print(f"  using cached {ZIP_PATH}")
        return
    print("  downloading ~319MB, this takes a few minutes...")
    req = urllib.request.Request(ZIP_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=600) as resp, open(ZIP_PATH, "wb") as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    print(f"  downloaded to {ZIP_PATH}")


def stream_matches():
    proc = subprocess.Popen(
        f"unzip -p '{ZIP_PATH}' UO.xml | iconv -f windows-1251 -t utf-8",
        shell=True, stdout=subprocess.PIPE, bufsize=2 * 1024 * 1024,
    )
    buf = b""
    matches = []
    mb = 0
    while True:
        chunk = proc.stdout.read(2 * 1024 * 1024)
        if not chunk:
            break
        buf += chunk
        while True:
            start = buf.find(b"<SUBJECT>")
            if start == -1:
                break
            end = buf.find(b"</SUBJECT>", start)
            if end == -1:
                break
            end += len(b"</SUBJECT>")
            record = buf[start:end]
            buf = buf[end:]
            text = record.decode("utf-8", errors="replace")
            if KEYWORD in text.lower():
                name_m = re.search(r"<NAME>(.*?)</NAME>", text, re.S)
                stan_m = re.search(r"<STAN>(.*?)</STAN>", text, re.S)
                edrpou_m = re.search(r"<EDRPOU>(.*?)</EDRPOU>", text, re.S)
                name = (name_m.group(1) if name_m else "").replace("&quot;", '"').replace("&apos;", "'")
                stan = stan_m.group(1) if stan_m else ""
                if any(x in stan for x in EXCLUDE_STAN_SUBSTR):
                    continue
                matches.append({"name": name.strip(), "edrpou": edrpou_m.group(1) if edrpou_m else ""})
        mb += 2
        if mb % 200 == 0:
            print(f"  processed ~{mb}MB, {len(matches)} matches so far...")
    proc.wait()
    return matches


def geocode(query):
    params = {"q": query, "format": "json", "limit": 1}
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.loads(resp.read())
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception as e:
        print(f"  geocode failed for {query!r}: {e}")
    return None


def main():
    print("Fetching Ukraine Unified State Register (UO/legal entities export)...")
    download_zip()
    matches = stream_matches()
    print(f"\n{len(matches)} active matches found")

    resources = []
    for m in matches:
        place = next((p for p in KNOWN_PLACES if p in m["name"]), None)
        coords = None
        address = "Ukraine"
        if place:
            city = PLACE_TO_CITY[place]
            address = f"{city}, Ukraine"
            coords = geocode(address)
            time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec

        entry = {
            "name": m["name"],
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": "Registered organization in Ukraine's Unified State Register of Legal Entities.",
            "address": address,
        }
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        resources.append(entry)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} geocoded")


if __name__ == "__main__":
    main()
