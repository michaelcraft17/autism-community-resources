#!/usr/bin/env python3
"""
Netherlands DUO special-education sites (dataset adressen_so, "Adressen van vestigingen in het speciaal onderwijs", CC-BY).
  https://onderwijsdata.duo.nl/api/3/action/package_show?id=adressen_so  -> vestigingenso.csv (900 sites, no personal fields)
Core: (V)SO / SO / VSO special schools (639). Broad: SBAO special primary schools (261, owner-approved).
Located with the keyless PDOK Locatieserver by postcode + house number (cache: tools/netherlands_duo_scratch/pdok_cache.jsonl).
Id nl-duo:<VESTIGINGSCODE>. Many sites share a school-board website; ids, not domains, identify them.
Output: new_resources_netherlands_duo.json   Raw: tools/netherlands_duo_scratch/vestigingenso.csv
"""
import collections
import csv
import io
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "netherlands_duo_scratch")
PKG = "https://onderwijsdata.duo.nl/api/3/action/package_show?id=adressen_so"
CSV_NAME = "vestigingenso.csv"
SRC = "Netherlands DUO special education sites (onderwijsdata.duo.nl, CC-BY)"
PDOK = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?"
CLUSTER = {"1": "visual impairment", "2": "hearing or language/speech difficulties",
           "3": "physical, intellectual or long-term illness needs", "4": "behavioural or psychiatric needs (where most autism provision sits)"}


def fetch():
    p = os.path.join(SCRATCH, CSV_NAME)
    if not os.path.exists(p):
        pkg = json.loads(rc.get(PKG))["result"]
        url = next(r["url"] for r in pkg["resources"] if r["url"].endswith("/" + CSV_NAME))
        rc.download(url, p)
    return list(csv.DictReader(io.StringIO(open(p, encoding="utf-8-sig").read())))


class Pdok:
    def __init__(self, path):
        self.path, self.cache = path, {}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                d = json.loads(line)
                self.cache[d["q"]] = d["c"]

    def locate(self, q, fq="type:adres"):
        key = f"{q}|{fq}"
        if key in self.cache:
            return self.cache[key]
        try:
            d = json.loads(rc.get(PDOK + urllib.parse.urlencode({"q": q, "fq": fq, "rows": 1, "fl": "centroide_ll"}), delay=0.1, timeout=30))
        except Exception as e:  # noqa: BLE001
            rc.note_failure("pdok", f"{q}: {e!r}")
            return None  # not cached: a failed lookup is retried next run
        docs = d["response"]["docs"]
        c = None
        if docs:
            m = re.match(r"POINT\(([-\d.]+) ([-\d.]+)\)", docs[0]["centroide_ll"])
            c = [float(m.group(2)), float(m.group(1))]
        self.cache[key] = c
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"q": key, "c": c}) + "\n")
        return c


def main():
    rows = fetch()
    rc.STATUS["input"] = "DUO adressen_so vestigingenso.csv"
    pdok = Pdok(os.path.join(SCRATCH, "pdok_cache.jsonl"))
    out, nogeo, approx = [], 0, 0
    for r in rows:
        code, kind = r["VESTIGINGSCODE"].strip(), r["SOORT PRIMAIR ONDERWIJS"].strip()
        pc = re.sub(r"\s", "", r["POSTCODE"]).upper()
        nr = r["HUISNUMMER-TOEVOEGING"].strip()
        num = re.match(r"\d+", nr)
        hit = pdok.locate(f"postcode:{pc} AND huisnummer:{num.group()}") if num else None
        if not hit:
            hit = pdok.locate(f"postcode:{pc}", fq="type:postcode")
            approx += bool(hit)
        if not hit or not rc.plausible("NL", *hit):
            nogeo += 1
            continue
        street = rc.clean(f"{r['STRAATNAAM']} {nr}")
        addr = f"{street}, {pc[:4]} {pc[4:]} {r['PLAATSNAAM'].title()}, Netherlands"
        sbao = kind == "SBAO"
        cl = r["CLUSTER"].strip()
        what = "Special primary school (SBAO)" if sbao else "Special education school"
        desc = f"{what} (DUO register, {rc.clean(r['DENOMINATIE']).lower() or 'denomination n/a'})"
        if cl and not sbao:
            desc += "; cluster " + cl + ": " + "; ".join(CLUSTER[c] for c in cl.split("/") if c in CLUSTER)
        phone = re.sub(r"\D", "", r["TELEFOONNUMMER"])
        phone = phone if phone and not phone.startswith("06") else None
        web = r["INTERNETADRES"].strip()
        web = rc.clean_url(web if web.lower().startswith("http") else "http://" + web) if web else None
        out.append(rc.entry(rc.clean(r["VESTIGINGSNAAM"]), SRC, "education", ["Special education", "Education"], desc + ".",
                            address=addr, phone=phone, website=web, lat=hit[0], lng=hit[1], external_id=f"nl-duo:{code}",
                            breadth="broad" if sbao else "core", scope="general"))
    print(f"{len(rows)} sites; {len(out)} placed ({approx} at postcode centroid); {nogeo} without a location")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_netherlands_duo.json"), out)
    print(collections.Counter(e["breadth"] for e in fin))
    rc.spot_check(fin, 8, fields=("name", "address", "external_id"))


if __name__ == "__main__":
    main()
