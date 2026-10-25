#!/usr/bin/env python3
"""
England & Wales Charity Commission register, "What: Disability" classification layer (BROAD tier).
Bulk extracts (keyless, Open Government Licence): publicextract.charity.zip + publicextract.charity_classification.zip from
ccewuksprdoneregsadata1.blob.core.windows.net/data/txt/. ~42,700 charities carry the classification; ~27,000 are registered.
uk_charity_regulators_fetch.py already holds the ~470 autism-matched charities (no ids; the merge removes overlap by name + city).

Selection: registered main charities (linked number 0) with a postcode, classified Disability, and
  * at most 5 "What" classifications (the many-purpose charities that tick everything are noise) -- or a disability word in
    the name, and
  * a disability word in the name or the activities text, and
  * latest income of at least GBP 25,000 (smaller charities are mostly run from a volunteer's home; the postcode would point at a house).
Grant-making funds and "relief in need" trusts are dropped by name. Located with postcodes.io (bulk, keyless; cache
postcodes_cache.jsonl) at full-postcode level; a postcode that does not resolve is dropped. Phone numbers and e-mails are never
read; the activities text is shortened to its first 220 characters. Id ccew:<registered number>. Scope "general", breadth broad.
Output: new_resources_ccew_disability.json   Raw: tools/ccew_disability_scratch/*.txt
"""
import csv
import io
import json
import os
import re
import sys
import zipfile
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

csv.field_size_limit(10 ** 9)
SCRATCH = os.path.join(rc.REPO, "tools", "ccew_disability_scratch")
BASE = "https://ccewuksprdoneregsadata1.blob.core.windows.net/data/txt/publicextract.{}.zip"
SRC = "England & Wales Charity Commission register (Disability classification)"
DISABILITY_NAME = re.compile(r"disab|autis|asperger|special needs|learning difficult|down'?s? syndrome|blind|deaf|hearing|sight|wheelchair|"
                             r"mencap|scope\b|cerebral|palsy|dyslex|adhd|epilep|muscular|stroke|multiple sclerosis|parkinson|"
                             r"sensory|mobility|accessib|inclusi|respite|carers?\b|handicap|enable\b|sense\b|shine\b|riding for the", re.I)
GRANT = re.compile(r"\b(relief[- ]in[- ]need|educational foundation|memorial fund|charitable trust|settlement|bequest|legacy|will trust)\b", re.I)
DISABILITY_TEXT = re.compile(r"disab|autis|asperger|special (educational )?needs|learning difficult|impair|blind|deaf|hearing loss|wheelchair|"
                             r"cerebral|palsy|dyslex|adhd|epilep|down'?s? syndrome|neurodiver|sensory|handicap", re.I)
SCHOOL = re.compile(r"\b(school|college|academy|nursery)\b", re.I)
MIN_INCOME = 25000
MAX_WHAT = 5


def extract(kind):
    out = os.path.join(SCRATCH, f"publicextract.{kind}.txt")
    if not os.path.exists(out):
        os.makedirs(SCRATCH, exist_ok=True)
        z = os.path.join(SCRATCH, f"{kind}.zip")
        rc.download(BASE.format(kind), z, timeout=900)
        with zipfile.ZipFile(z) as zf:
            with zf.open(f"publicextract.{kind}.txt") as src, open(out, "wb") as dst:
                dst.write(src.read())
        os.remove(z)
    return out


def rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f, delimiter="\t")


def title(s):
    s = rc.clean(s)
    return s.title() if s.isupper() else s


def locate(postcodes):
    """postcodes.io bulk lookup (100 per request), cached; {postcode: (lat, lng) or None}."""
    cp = os.path.join(SCRATCH, "postcodes_cache.jsonl")
    cache = {}
    if os.path.exists(cp):
        for line in open(cp, encoding="utf-8"):
            d = json.loads(line)
            cache[d["p"]] = tuple(d["c"]) if d["c"] else None
    todo = sorted(p for p in postcodes if p not in cache)
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        try:
            res = json.loads(rc.get("https://api.postcodes.io/postcodes", data=json.dumps({"postcodes": chunk}).encode(),
                                    headers={"Content-Type": "application/json"}, timeout=60, retries=3))["result"]
        except Exception as e:  # noqa: BLE001
            rc.note_failure("postcodes.io", f"batch {i}: {e!r}")
            continue
        got = {}
        for it in res:
            r = it.get("result")
            got[it["query"]] = (r["latitude"], r["longitude"]) if r and r.get("latitude") is not None else None
        with open(cp, "a", encoding="utf-8") as f:
            for p in chunk:
                if p in got:
                    cache[p] = got[p]
                    f.write(json.dumps({"p": p, "c": got[p]}) + "\n")
        if (i // 100) % 25 == 0:
            print(f"  postcodes {i}/{len(todo)}", flush=True)
    return cache


def main():
    cls = extract("charity_classification")
    ch = extract("charity")
    dis, nwhat = set(), collections.Counter()
    for r in rows(cls):
        if r["linked_charity_number"] != "0" or r["classification_type"] != "What":
            continue
        nwhat[r["registered_charity_number"]] += 1
        if r["classification_code"] == "104":
            dis.add(r["registered_charity_number"])
    if len(dis) < 30000:
        sys.exit(f"CCEW: only {len(dis)} charities classified Disability, expected ~42,700 -- layout changed? nothing written")
    cands, skip, n = {}, collections.Counter(), 0
    for r in rows(ch):
        n += 1
        num = r["registered_charity_number"]
        if r["linked_charity_number"] != "0" or num not in dis or r["charity_registration_status"] != "Registered":
            continue
        name = rc.clean(r["charity_name"])
        pc = re.sub(r"\s+", " ", r["charity_contact_postcode"].strip().upper())
        if not pc:
            skip["no postcode"] += 1
            continue
        try:
            income = float(r["latest_income"] or 0)
        except ValueError:
            income = 0
        if income < MIN_INCOME:
            skip["income under GBP 25k"] += 1
            continue
        if not (DISABILITY_NAME.search(name) or DISABILITY_TEXT.search(r["charity_activities"])):
            skip["no disability word in name or activities"] += 1
            continue
        if nwhat[num] > MAX_WHAT and not DISABILITY_NAME.search(name):
            skip["many purposes, no disability word in name"] += 1
            continue
        if re.match(r"\s*(c/o|care of)\b", r["charity_contact_address1"], re.I):   # care of a solicitor / accountant / person
            skip["c/o address"] += 1
            continue
        if GRANT.search(name):
            skip["grant-making / trust name"] += 1
            continue
        cands[num] = (r, name, pc)
    rc.STATUS["input"] = f"CCEW charity {n} rows, {len(dis)} Disability"
    print(f"{n} charity rows; {len(cands)} candidates; skipped {dict(skip)}")
    loc = locate({pc for _, _, pc in cands.values()})
    out, nogeo = [], 0
    for num, (r, name, pc) in cands.items():
        hit = loc.get(pc)
        if not hit or not rc.plausible("GB", *hit):
            nogeo += 1
            continue
        lines = [title(r[f"charity_contact_address{i}"]) for i in range(1, 6) if rc.clean(r[f"charity_contact_address{i}"])]
        addr = ", ".join(lines + [pc])
        act = rc.clean(r["charity_activities"])
        act = (act[:220].rsplit(" ", 1)[0] + "...") if len(act) > 220 else act
        out.append(rc.entry(title(name), SRC, "education" if SCHOOL.search(name) else "general_support", ["Information & Support"],
                            f"Registered charity {num} (England & Wales), classified Disability." + (f" {act}" if act else ""),
                            address=addr, website=rc.clean_url(r["charity_contact_web"]), lat=hit[0], lng=hit[1],
                            external_id=f"ccew:{num}", breadth="broad", scope="general"))
    print(f"{len(out)} built; {nogeo} dropped (postcode did not resolve)")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_ccew_disability.json"), out)
    rc.spot_check(fin, 25, fields=("name", "address", "type"))


if __name__ == "__main__":
    main()
