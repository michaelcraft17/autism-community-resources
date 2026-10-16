#!/usr/bin/env python3
"""
Japan: child disability-welfare service offices from WAM NET's open data (the Welfare and Medical Service Agency's
register of designated disability-welfare offices; free secondary use under the site's terms):

    https://www.wam.go.jp/content/files/pcpub/top/sfkopendata/<YYYYMM>/sfkopendata_<YYYYMM>_<service code>.zip
    (page: https://www.wam.go.jp/content/wamnet/pcpub/top/sfkopendata/ ; published end of March and end of September;
     202609 was not posted on 2026-10-15, so 202603 is used)

Core = the child-service codes 63-70 (42,261 office rows): 63 jido hattatsu shien, 64 iryogata jido hattatsu shien,
65 hokago-tou day service, 66 kyotaku houmon-gata, 67 hoikusho-tou houmon shien, 68/69 child residential facilities,
70 shogaiji sodan shien. The other 20 service codes (adult services, ~92,500 offices) are left for a later broad batch.
Every row carries latitude/longitude. Rows with the same office name and address are one listing (a site often runs several
services); its external_id is wam:<lowest office number>. Names and addresses are NFKC-normalised (full-width digits/Latin).
Child residential facilities are staffed institutions and are pinned; corporation names are legal entities.

Usage:  python3 tools/wam_fetch.py [YYYYMM]          writes new_resources_wam.json
"""
import csv
import glob
import io
import os
import sys
import unicodedata
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "wam_scratch")
SOURCE = "Japan WAM NET (Welfare and Medical Service Agency) - disability-welfare service office open data"
CODES = [63, 64, 65, 66, 67, 68, 69, 70]
SERVICE = {   # service name -> (rank for the primary type, type, English services, English gloss)
    "児童発達支援": (0, "therapy", ["Early Intervention"], "child development support"),
    "医療型児童発達支援": (0, "therapy", ["Early Intervention", "Rehabilitation"], "medical-type child development support"),
    "放課後等デイサービス": (0, "therapy", ["After-School Programs"], "after-school day service"),
    "居宅訪問型児童発達支援": (0, "therapy", ["Early Intervention", "Home-Based Support"], "home-visit child development support"),
    "保育所等訪問支援": (1, "therapy", ["Inclusion Support"], "nursery/school visit support"),
    "福祉型障害児入所施設": (2, "social", ["Residential & Social Care"], "welfare-type residential facility for children with disabilities"),
    "医療型障害児入所施設": (2, "social", ["Residential & Social Care", "Rehabilitation"], "medical-type residential facility for children with disabilities"),
    "障害児相談支援": (3, "general_support", ["Information & Support", "Case Management"], "consultation and support planning for children with disabilities"),
}


def nf(s):
    return rc.clean(unicodedata.normalize("NFKC", s or ""))


def main():
    ym = sys.argv[1] if len(sys.argv) > 1 else "202603"
    sites, by_no = {}, {}
    nrows = 0
    for code in CODES:
        zp = rc.download(f"https://www.wam.go.jp/content/files/pcpub/top/sfkopendata/{ym}/sfkopendata_{ym}_{code}.zip",
                         os.path.join(SCRATCH, f"sfkopendata_{ym}_{code}.zip"))
        with zipfile.ZipFile(zp) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            for r in csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig", newline="")):
                nrows += 1
                try:
                    lat, lng = float(r["事業所緯度"]), float(r["事業所経度"])
                except ValueError:
                    continue
                if not rc.plausible("JP", lat, lng):
                    continue
                # one record per office number (the register's own key) ...
                s = by_no.setdefault(r["事業所番号"], {"name": nf(r["事業所の名称"]), "addr": nf(r["事業所住所（市区町村）"]) + nf(r["事業所住所（番地以降）"]),
                                                    "lat": lat, "lng": lng, "phone": nf(r["事業所電話番号"]), "web": r["事業所URL"] or r["法人URL"],
                                                    "corp": nf(r["法人の名称"]), "svc": set(), "nos": {r["事業所番号"]}})
                s["svc"].add(r["サービス種別"])
    # ... then offices with the same name and address become one listing (the app shows one listing per name|address|source)
    for no, o in by_no.items():
        s = sites.setdefault((o["name"], o["addr"]), o)
        if s is not o:
            s["svc"] |= o["svc"]
            s["nos"] |= o["nos"]
    print(f"WAM {ym}: {nrows} service rows -> {len(by_no)} office numbers -> {len(sites)} listings")
    entries = []
    for (name, addr), s in sites.items():
        svcs = sorted(s["svc"], key=lambda x: SERVICE[x][0])
        typ = SERVICE[svcs[0]][1]
        services = list(dict.fromkeys(x for v in svcs for x in SERVICE[v][2]))
        gloss = "; ".join(f"{v} ({SERVICE[v][3]})" for v in svcs)
        desc = f"{gloss}." + (f" Operated by {s['corp']}." if s["corp"] else "")
        entries.append(rc.entry(name, SOURCE, typ, services, desc, address=addr, phone=s["phone"] or None,
                                website=rc.clean_url(s["web"]), lat=s["lat"], lng=s["lng"], external_id=f"wam:{min(s['nos'])}", scope="general"))
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_wam.json"), entries)
    rc.spot_check(out, 12, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
