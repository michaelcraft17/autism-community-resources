#!/usr/bin/env python3
"""
Scotland -- OSCR Scottish Charity Register (Open Government Licence), daily ZIP of one CSV:
    https://www.oscr.org.uk/download/charity-register

Core: Active charities whose name / known-as matches a disability term (autism, Asperger, disab*, Down's syndrome,
dyslexia, deaf, blind, cerebral palsy, ADHD, special needs, learning difficulties, ...).
The 5,000 charities that merely tick the "disabled people" beneficiary box are the broad noisy set and are not merged.

Locations: ONS postcode centroids from postcodes.io (keyless, not cached; outward-code centroid when the full postcode
is unknown). Principal-office addresses of small charities are often a trustee's home, so for a c/o or PO-box address
or an unincorporated association the address shown is the main operating location plus the outward code, and the pin
is the outward-code centroid -- never the full postcode. If that outward-code lookup fails the row is skipped:
counted with rc.note_failure, or just printed when postcodes.io does not know the outward code (404). Outward-code
lookups are made once per code per run. A failed bulk postcode request stops the run (nothing is written).

Raw files (tools/oscr_scratch/, gitignored): oscr.zip (the download) and the CharityExport*.csv unzipped from it; an
existing CSV is used as is (tools/refresh_source.py deletes both before each fetch), and the run stops if there is none
after unzipping. The CSV name is printed and recorded as rc.STATUS["input"].
Output: new_resources_oscr.json
"""
import csv
import glob
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse

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


class LookupFailed(Exception):
    """postcodes.io gave no usable answer (5xx, timeout, connection error, bad body)."""


_OUTCODES = {}   # outward code -> (lat, lng), None when postcodes.io does not know it (404), or the error text


def outcode_lookup(oc):
    """Outward-code centroid, looked up once per code per run. None for an unknown outward code (404, or 400/410,
    printed); raises LookupFailed for any other failure, on every call for that code, so each affected row is counted.
    A refusal (401/403/451) is recorded by rc.get and stops the run."""
    if oc not in _OUTCODES:
        try:   # quoted: a stray non-ASCII or control character in a free-text postcode is a 404, not a client error
            r = json.loads(rc.get(f"https://api.postcodes.io/outcodes/{urllib.parse.quote(oc, safe='')}", delay=0.3))["result"]
            _OUTCODES[oc] = (r["latitude"], r["longitude"])
        except urllib.error.HTTPError as e:
            if e.code in rc.REFUSAL_CODES:
                raise
            _OUTCODES[oc] = None if e.code in (400, 404, 410) else repr(e)
        except Exception as e:  # noqa: BLE001
            _OUTCODES[oc] = repr(e)
        if _OUTCODES[oc] is None:
            print(f"  unknown outward code {oc} (not found)")
    c = _OUTCODES[oc]
    if isinstance(c, str):
        raise LookupFailed(f"outcode {oc}: {c}")
    return c


def postcode_lookup(pcs):
    """ONS postcode centroids via postcodes.io (open, keyless); outward-code centroid when the full postcode is unknown
    (e.g. PO-box postcodes). Returns (centroids, failed): failed maps a postcode whose outward-code fallback failed to
    the error, for the caller to count per row. A failed bulk request raises (rc.get has retried), stopping the run."""
    out, failed, pcs = {}, {}, sorted(set(pcs))
    for i in range(0, len(pcs), 100):
        d = json.loads(rc.get("https://api.postcodes.io/postcodes", data=json.dumps({"postcodes": pcs[i:i + 100]}).encode(),
                               headers={"Content-Type": "application/json"}, method="POST", delay=0.3))
        for x in d["result"]:
            if x["result"]:
                out[x["query"]] = (x["result"]["latitude"], x["result"]["longitude"])
    for pc in pcs:
        if pc not in out:
            try:
                c = outcode_lookup(pc.split()[0])
            except LookupFailed as e:
                failed[pc] = str(e)
                continue
            if c:
                out[pc] = c
    return out, failed


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
    found = sorted(glob.glob(os.path.join(SCRATCH, "CharityExport*.csv")))
    if not found:
        sys.exit("OSCR: no CharityExport*.csv in tools/oscr_scratch/ after unzipping oscr.zip -- nothing written")
    path = found[-1]
    print(f"OSCR: using {os.path.basename(path)}")
    rc.STATUS["input"] = f"OSCR {os.path.basename(path)}"
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8-sig", errors="replace"))]
    rows = [r for r in rows if r["Charity Status"] == "Active" and (NAME_RE.search(rc.clean(r["Charity Name"])) or NAME_RE.search(rc.clean(r["Known As"])))]
    look, failed = postcode_lookup([norm_pc(r["Postcode"]) for r in rows if rc.clean(r["Postcode"])])
    entries, nogeo, n, nocode, nfail = [], 0, 0, 0, 0
    for r in rows:
        if r["Charity Status"] != "Active":
            continue
        name, known = rc.clean(r["Charity Name"]), rc.clean(r["Known As"])
        if not (NAME_RE.search(name) or NAME_RE.search(known)) or SKIP_RE.search(name):
            continue
        n += 1
        pc = norm_pc(r["Postcode"])
        if pc in failed:
            nfail += 1
            rc.note_failure("postcodes.io", f"{r['Charity Number']}: {failed[pc]}")
            continue
        hit = look.get(pc)
        if not hit or not rc.plausible("GB", *hit):
            nogeo += 1
            continue
        raw = rc.clean(r["Principal Office/Trustees Address"])
        # c/o addresses, PO boxes and small unincorporated associations (usually a trustee's home) are shown at outward-code level
        form_raw = rc.clean(r["Constitutional Form"]).lower()
        private = bool(re.match(r"\s*(c/o|care of)\b|p\.? ?o\.? ?box", raw, re.I)) or not raw or form_raw.startswith("unincorporated")
        if private:   # outward-code centroid only; never fall back to the full postcode
            oc = pc.split()[0]
            try:
                hit = outcode_lookup(oc)
            except LookupFailed as e:
                nfail += 1
                rc.note_failure("postcodes.io", f"{r['Charity Number']}: {e}")
                continue
            if not hit or not rc.plausible("GB", *hit):
                nocode += 1
                print(f"  {r['Charity Number']}: private address and no centroid for outward code {oc}, skipped")
                continue
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
    print(f"{n} active charities matched; {nogeo} without a geocode, {nocode} private rows without an outward-code centroid, "
          f"{nfail} skipped after a failed postcodes.io lookup (counted)")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_oscr.json"), entries)
    rc.spot_check(out, 30, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
