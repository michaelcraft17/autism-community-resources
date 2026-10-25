#!/usr/bin/env python3
"""
Japan -- MEXT school-code list (school basic survey codes), special-support schools (tokubetsu shien gakko, school type
E1: schools for pupils with intellectual disability, physical disability, visual / hearing impairment, ...):
    index: https://www.mext.go.jp/b_menu/toukei/mext_01087.html  (CSV links ..._2-1.csv, ..._2-2.csv, ..._4.csv; the
    newest dated link of each is used; E1 rows are spread across them)
Usage: python3 tools/mext_fetch.py

Core: rows with school type E1 and no abolition date, one per school code (学校コード, the stable id); branch schools
(分校) are separate codes and stay separate. Addresses are NFKC-normalised. Geocoding: GSI address search
(msearch.gsi.go.jp, keyless); a hit is accepted only when its title starts with the same prefecture + municipality as
the address (so a wrong-town hit is never kept) and is inside Japan; the match precision (block level vs. town level)
is counted. Cache: tools/mext_scratch/geocode_cache.jsonl. Output: new_resources_mext.json
"""
import csv
import io
import json
import os
import re
import sys
import unicodedata
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "mext_scratch")
INDEX = "https://www.mext.go.jp/b_menu/toukei/mext_01087.html"
SOURCE = "Japan MEXT school code list (special-support schools)"
GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="
OWNER = {"1": "national", "2": "public", "3": "private"}


def nf(s):
    return rc.clean(unicodedata.normalize("NFKC", s or ""))


class Gsi:
    def __init__(self, path):
        self.path, self.cache = path, {}
        self.failures = 0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                d = json.loads(line)
                self.cache[d["q"]] = d["c"]

    def query(self, q):
        """[(lat, lng, title)] for the query, cached; None when the lookup could not be made."""
        if q in self.cache:
            return self.cache[q]
        if self.failures >= 10:
            return None
        try:
            d = json.loads(rc.get(GSI + urllib.parse.quote(q), delay=0.2, timeout=30, retries=2))
        except Exception as e:  # noqa: BLE001
            self.failures += 1
            rc.note_failure("gsi", f"{q}: {e!r}")
            return None
        self.failures = 0
        res = [[f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0], f["properties"]["title"]] for f in d[:3]]
        self.cache[q] = res
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"q": q, "c": res}, ensure_ascii=False) + "\n")
        return res

    def locate(self, addr):
        """(lat, lng, precision) with precision 'block' | 'town', or None. Tries the address, then the part before its
        first block number; requires the hit title to start with the address's prefecture + municipality."""
        addr = re.sub(r"^(.{2,4}?[都道府県])[^市区町村]{1,5}郡", r"\1", addr)   # GSI titles omit the 郡 (district)
        m = re.match(r"(.{2,4}?[都道府県])(.+?[市区町村])", addr)
        if not m:
            return None
        head = m.group(1) + m.group(2)
        tries = [("block", addr), ("town", re.split(r"[0-9]", addr, maxsplit=1)[0].rstrip("字大")), ("town", head)]
        for prec, q in tries:
            if len(q) <= len(head) and q != head:
                continue
            res = self.query(q)
            if res is None:
                return None
            for lat, lng, title in res:
                if title.startswith(head) and rc.plausible("JP", lat, lng):
                    return lat, lng, prec if len(title) > len(head) else "town"
        return None


def main():
    idx = rc.get(INDEX, browser=True).decode("utf-8", "replace")
    urls = []
    for suffix in ("2-1", "2-2", "4"):
        m = re.findall(rf'href="(/content/\d+-mxt_chousa01-000011635_{suffix}\.csv)"', idx)
        if not m:
            sys.exit(f"MEXT: no link for file _{suffix}.csv on the index page -- nothing written")
        urls.append("https://www.mext.go.jp" + max(m))
    schools = {}
    for u in urls:
        path = rc.download(u, os.path.join(SCRATCH, os.path.basename(u)))
        rows = list(csv.reader(io.StringIO(open(path, encoding="utf-8-sig").read())))
        for r in rows[2:]:
            if len(r) >= 10 and r[1].startswith("E1") and not r[9].strip():
                schools.setdefault(r[0], r)
    rc.STATUS["input"] = "MEXT " + ", ".join(os.path.basename(u) for u in urls)
    print(f"{len(schools)} active special-support schools")
    gsi = Gsi(os.path.join(SCRATCH, "geocode_cache.jsonl"))
    out, nogeo, town = [], 0, 0
    for code, r in schools.items():
        addr = nf(r[6])
        hit = rc.prior_coords(f"mext:{code}", addr)
        prec = "block"
        if not hit:
            g = gsi.locate(addr)
            if not g:
                nogeo += 1
                continue
            hit, prec = (g[0], g[1]), g[2]
        town += prec == "town"
        pc = re.sub(r"\D", "", r[7])
        address = (f"〒{pc[:3]}-{pc[3:]} " if len(pc) == 7 else "") + addr
        branch = r[4].startswith("2")
        owner = OWNER.get(r[3][:1], "")
        desc = (f"Special-support school (tokubetsu shien gakko){', branch campus' if branch else ''}, {owner} school; "
                f"MEXT school code {code}.").replace(", ,", ",")
        out.append(rc.entry(nf(r[5]), SOURCE, "education", ["Special Education"], desc, address=address,
                            lat=hit[0], lng=hit[1], external_id=f"mext:{code}", scope="general"))
    print(f"{len(out)} located ({town} at town or municipality level); {nogeo} without an acceptable GSI match")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_mext.json"), out)
    rc.spot_check(fin, 25, fields=("name", "address"))


if __name__ == "__main__":
    main()
