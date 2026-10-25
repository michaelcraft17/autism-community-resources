#!/usr/bin/env python3
"""
IRS Exempt Organizations Business Master File, disability NTEE layer (eo1-eo4.csv, irs.gov/pub/irs-soi/, keyless, ~340 MB).
The autism codes G84/H84 are built by irs_bmf_ntee_fetch.py; this adds the disability codes it left out:
  P82 developmentally disabled centres  -> social       B28 special education       -> education
  R23 disabled persons' rights          -> advocacy     P86 blind / visually impaired, P87 deaf / hard of hearing -> social
  G25 birth defects / genetic conditions (incl. Down syndrome) -> social
NOT built: E50 (rehabilitative care; equine therapy, dyslexia groups) and P80 (HUD housing shells).
Selection: STATUS 01 (active) only. A row is dropped when its street is a PO box / PMB / "c/o", or an apartment / unit number
(residential address), or has no street number, or reports no assets and no income (dormant; usually a volunteer's home); EINs already in the dataset (the 768 autism-code rows) are skipped.
Located with the US Census Bureau batch geocoder (official, keyless; Public_AR_Current benchmark, 2,000 rows per request,
cache irs_ntee_disability_scratch/census_cache.jsonl). Only an "Exact" match is pinned; other rows are dropped, never moved
to a ZIP centroid. Scope "general" (not autism-specific). Id irs-ntee:<EIN>.
Output: new_resources_irs_ntee_disability.json   Raw: tools/irs_ntee_disability_scratch/eo[1-4].csv
"""
import collections
import csv
import glob
import io
import json
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

csv.field_size_limit(10 ** 9)
SCRATCH = os.path.join(rc.REPO, "tools", "irs_ntee_disability_scratch")
SRC = "IRS Exempt Organizations Business Master File (NTEE disability layer)"
BASE = "https://www.irs.gov/pub/irs-soi/eo{}.csv"
CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CODES = {   # NTEE -> (type, services, description)
    "P82": ("social", ["Residential & Social Care", "Day programs"], "developmental disabilities services"),
    "B28": ("education", ["Special education"], "special education"),
    "R23": ("advocacy", ["Advocacy"], "disability rights and advocacy"),
    "P86": ("social", ["Information & Support"], "services for blind and visually impaired people"),
    "P87": ("social", ["Information & Support"], "services for deaf and hard-of-hearing people"),
    "G25": ("social", ["Information & Support", "Peer Support"], "birth defects and genetic conditions (including Down syndrome)"),
}
NOT_STREET = re.compile(r"^\s*(p\.?\s?o\.?\s*box|pmb|box\b|c/o|co\s|care of|attn)", re.I)
RESIDENTIAL = re.compile(r"\b(apt|apartment|unit|#)\s*\w", re.I)
BATCH = 2000


def title(s):
    t = rc.clean(s).title()
    t = re.sub(r"(?<=[A-Za-z])'S\b", "'s", t)
    t = re.sub(r"\b(Llc|Lp|Inc|Ii|Iii|Iv|Usa|Us|Ymca|Ymha|Arc|Nw|Ne|Sw|Se)\b", lambda m: m.group().upper() if m.group() not in ("Inc", "Arc") else m.group(), t)
    return t


def eo_files():
    os.makedirs(SCRATCH, exist_ok=True)
    return [rc.download(BASE.format(i), os.path.join(SCRATCH, f"eo{i}.csv"), timeout=900) for i in range(1, 5)]


def known_eins():
    eins = set()
    for f in glob.glob(os.path.join(rc.REPO, "data", "us", "*.json")):
        for e in json.load(open(f, encoding="utf-8")):
            if str(e.get("external_id", "")).startswith("irs-ntee:"):
                continue   # this fetcher's own rows are re-fetched, not skipped
            eins.update(re.findall(r"\bEIN (\d{9})\b", e.get("description", "")))
            if e.get("ein"):
                eins.add(str(e["ein"]))
    return eins


def census_batch(rows, cache):
    """rows: [(id, street, city, state, zip)]; fills cache[id] = (lat, lng) | None for exact matches / misses."""
    todo = [r for r in rows if r[0] not in cache]
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        buf = io.StringIO()
        csv.writer(buf).writerows(chunk)
        b = uuid.uuid4().hex
        body = (f'--{b}\r\nContent-Disposition: form-data; name="benchmark"\r\n\r\nPublic_AR_Current\r\n'
                f'--{b}\r\nContent-Disposition: form-data; name="addressFile"; filename="a.csv"\r\nContent-Type: text/csv\r\n\r\n'
                f'{buf.getvalue()}\r\n--{b}--\r\n').encode("utf-8")
        try:
            raw = rc.get(CENSUS, data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"}, timeout=600, retries=2)
        except Exception as e:  # noqa: BLE001
            rc.note_failure("census", f"batch {i}: {e!r}")
            continue
        got = {}
        for r in csv.reader(io.StringIO(raw.decode("utf-8", "replace"))):
            if len(r) < 6:
                continue
            try:
                got[r[0]] = tuple(float(x) for x in reversed(r[5].split(","))) if r[2] == "Match" and r[3] == "Exact" and r[5] else None
            except ValueError:
                got[r[0]] = None
        missing = [r[0] for r in chunk if r[0] not in got]
        if len(got) < len(chunk) * 0.9:
            rc.note_failure("census", f"batch {i}: only {len(got)} of {len(chunk)} rows answered")
            continue   # not cached: retried on a later run
        with open(os.path.join(SCRATCH, "census_cache.jsonl"), "a", encoding="utf-8") as f:
            for r in chunk:
                cache[r[0]] = got.get(r[0])
                f.write(json.dumps({"id": r[0], "c": cache[r[0]]}) + "\n")
        print(f"  census {min(i + BATCH, len(todo))}/{len(todo)} (unanswered {len(missing)})", flush=True)


def main():
    paths = eo_files()
    have = known_eins()
    cands, skip = {}, collections.Counter()
    n = 0
    for p in paths:
        with open(p, encoding="latin-1", newline="") as f:
            for r in csv.DictReader(f):
                n += 1
                code = (r["NTEE_CD"] or "")[:3]
                if code not in CODES:
                    continue
                if r["STATUS"] != "01":
                    skip["inactive"] += 1
                    continue
                street = rc.clean(r["STREET"])
                if not street or NOT_STREET.search(street):
                    skip["po box / c-o"] += 1
                    continue
                if RESIDENTIAL.search(street) or not re.match(r"\d", street):
                    skip["apartment or no street number"] += 1
                    continue
                if r["ASSET_CD"] in ("0", "") and r["INCOME_CD"] in ("0", ""):   # no assets and no income: dormant, usually a volunteer's home address
                    skip["no assets or income"] += 1
                    continue
                if r["EIN"] in have:
                    skip["already in dataset"] += 1
                    continue
                cands[r["EIN"]] = (r, code, street)
    if n < 1_500_000:
        sys.exit(f"IRS BMF: only {n} rows scanned, expected ~1.97M -- files truncated? nothing written")
    rc.STATUS["input"] = f"IRS BMF {n} rows"
    print(f"{n} rows scanned; {len(cands)} candidates; skipped {dict(skip)}")
    cache = {}
    cp = os.path.join(SCRATCH, "census_cache.jsonl")
    if os.path.exists(cp):
        for line in open(cp, encoding="utf-8"):
            d = json.loads(line)
            cache[d["id"]] = tuple(d["c"]) if d["c"] else None
    census_batch([(ein, st, r["CITY"], r["STATE"], r["ZIP"][:5]) for ein, (r, _, st) in cands.items()], cache)
    out, nomatch = [], 0
    for ein, (r, code, st) in cands.items():
        loc = cache.get(ein)
        if not loc or not rc.plausible("US", *loc):
            nomatch += 1
            continue
        typ, svc, what = CODES[code]
        city = title(r["CITY"])
        out.append(rc.entry(title(r["NAME"]), SRC, typ, svc,
                            f"Tax-exempt organisation in {city}, {r['STATE']} (IRS NTEE {code}: {what}). EIN {ein}.",
                            address=f"{title(st)}, {city}, {r['STATE']} {r['ZIP'][:5]}", lat=loc[0], lng=loc[1],
                            external_id=f"irs-ntee:{ein}", scope="general"))
    print(f"{len(out)} built; {nomatch} dropped (no exact Census match)")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_irs_ntee_disability.json"), out)
    rc.spot_check(fin, 20, fields=("name", "address", "type", "description"))


if __name__ == "__main__":
    main()
