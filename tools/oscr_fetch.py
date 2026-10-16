#!/usr/bin/env python3
"""
Scotland -- OSCR Scottish Charity Register (Open Government Licence), daily ZIP of one CSV:
    https://www.oscr.org.uk/download/charity-register

Core: Active charities whose name / known-as matches a disability term (autism, Asperger, disab*, Down's syndrome,
dyslexia, deaf, blind, cerebral palsy, ADHD, special needs, learning difficulties, ...).
The 5,000 charities that merely tick the "disabled people" beneficiary box are the broad noisy set and are not merged.
Principal-office addresses of small charities are often a trustee's home, so a c/o address is replaced by the main
operating location and nothing is pinned finer than the postcode (Nominatim, cached; outward-code fallback).
Output: new_resources_oscr.json
"""
import csv
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "oscr_scratch")
URL = "https://www.oscr.org.uk/download/charity-register"
SOURCE = "Scotland OSCR Scottish Charity Register (Office of the Scottish Charity Regulator)"
NAME_RE = re.compile(
    r"autis|asperger|\bdisab|handicap|special needs|additional support needs|learning (disab|difficult)|intellectual|down'?s? syndrome|"
    r"dyslex|\bdeaf|\bblind|cerebral palsy|\badhd\b|\bepilep|tourette|neurodiver|neurodev|muscular dystrophy|spina bifida|"
    r"multiple sclerosis|\bsense scotland|enable scotland|\bcapability scotland|mencap|riding for the disabled|special olympics|"
    r"hearing loss|sight loss|visually impaired|wheelchair|paraplegi|brain injur|\bfasd\b", re.I)
SKIP_RE = re.compile(r"day ?care|nursery|preschool|play ?group|\bin (ethiopia|africa|india|kenya|uganda|malawi|nepal|romania|zambia|ghana)\b|\b(ethiopia|uganda|malawi|nepal|kenya)\b", re.I)


def postcode_lookup(pcs):
    """ONS postcode centroids via postcodes.io (open, keyless); outward-code centroid when the full postcode is unknown (e.g. PO-box postcodes)."""
    out, pcs = {}, sorted(set(pcs))
    for i in range(0, len(pcs), 100):
        d = json.loads(rc.get("https://api.postcodes.io/postcodes", data=json.dumps({"postcodes": pcs[i:i + 100]}).encode(),
                               headers={"Content-Type": "application/json"}, method="POST", delay=0.3))
        for x in d["result"]:
            if x["result"]:
                out[x["query"]] = (x["result"]["latitude"], x["result"]["longitude"])
    for pc in pcs:
        if pc not in out:
            oc = pc.split()[0]
            try:
                r = json.loads(rc.get(f"https://api.postcodes.io/outcodes/{oc}", delay=0.3))["result"]
                out[pc] = (r["latitude"], r["longitude"])
            except Exception:  # noqa: BLE001
                pass
    return out


def outcode_lookup(pc):
    try:
        r = json.loads(rc.get(f"https://api.postcodes.io/outcodes/{pc.split()[0]}", delay=0.3))["result"]
        return r["latitude"], r["longitude"]
    except Exception:  # noqa: BLE001
        return None


def norm_pc(s):
    s = re.sub(r"\s+", "", rc.clean(s).upper())
    return f"{s[:-3]} {s[-3:]}" if len(s) > 4 else s


def smart(s):
    s = rc.clean(s)
    return s.title() if s.isupper() else s


def main():
    if not glob.glob(os.path.join(SCRATCH, "CharityExport*.csv")):
        os.makedirs(SCRATCH, exist_ok=True)
        rc.download(URL, os.path.join(SCRATCH, "oscr.zip"))
        subprocess.run(["unzip", "-o", "-q", os.path.join(SCRATCH, "oscr.zip"), "-d", SCRATCH], check=True)
    csv.field_size_limit(10**8)
    path = sorted(glob.glob(os.path.join(SCRATCH, "CharityExport*.csv")))[-1]
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8-sig", errors="replace"))]
    rows = [r for r in rows if r["Charity Status"] == "Active" and (NAME_RE.search(rc.clean(r["Charity Name"])) or NAME_RE.search(rc.clean(r["Known As"])))]
    look = postcode_lookup([norm_pc(r["Postcode"]) for r in rows if rc.clean(r["Postcode"])])
    entries, nogeo, n = [], 0, 0
    for r in rows:
        if r["Charity Status"] != "Active":
            continue
        name, known = rc.clean(r["Charity Name"]), rc.clean(r["Known As"])
        if not (NAME_RE.search(name) or NAME_RE.search(known)) or SKIP_RE.search(name):
            continue
        n += 1
        pc = norm_pc(r["Postcode"])
        hit = look.get(pc)
        if not hit or not rc.plausible("GB", *hit):
            nogeo += 1
            continue
        raw = rc.clean(r["Principal Office/Trustees Address"])
        # c/o addresses, PO boxes and small unincorporated associations (usually a trustee's home) are shown at outward-code level
        form_raw = rc.clean(r["Constitutional Form"]).lower()
        private = bool(re.match(r"\s*(c/o|care of)\b|p\.? ?o\.? ?box", raw, re.I)) or not raw or form_raw.startswith("unincorporated")
        if private:
            hit = outcode_lookup(pc) or hit
        loc = rc.clean(r["Main Operating Location"]).split(",")[0]
        address = ", ".join(x for x in ((smart(loc) if private else raw), pc.split()[0] if private else "") if x)
        site = rc.clean(r["Website"])
        if site and not site.lower().startswith("http"):
            site = "http://" + site
        form = rc.clean(r["Constitutional Form"]).lower()
        typ = "advocacy" if re.search(r"association|society|council|federation|alliance|forum|network|mencap|enable|capability|sense", name, re.I) else "general_support"
        services = ["Advocacy", "Information & Support"] if typ == "advocacy" else ["Information & Support"]
        desc = f"Scottish registered charity ({r['Charity Number']}, {form}) with a disability-related name."
        entries.append(rc.entry(smart(name), SOURCE, typ, services, desc, address=address, website=rc.clean_url(site) if site else None,
                                lat=hit[0], lng=hit[1], external_id=f"oscr:{r['Charity Number']}",
                                scope=None if re.search(r"autis|asperger", name + known, re.I) else "general"))
    print(f"{n} active charities matched; {nogeo} without a geocode")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_oscr.json"), entries)
    rc.spot_check(out, 30, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
