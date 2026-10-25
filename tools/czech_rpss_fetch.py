#!/usr/bin/env python3
"""
Czechia MPSV RPSS (Registr poskytovatelu socialnich sluzeb), open data, refreshed daily.
  https://data.mpsv.cz/od/soubory/rpss/rpss.json  (99 MB; one item per registered service)  + code lists in /ciselniky/
Core only (no broad tier built): active services (`datumPoskytovaniDo` null) that are disability-specific by type
(personal assistance, guide/reader, homes for people with disabilities, sheltered housing, early intervention,
interpreting, social-therapy workshops) or list a disability target group (12-18, 31 = autism) on a type that is not
elderly-dominated (home care, seniors' homes, special-regime homes, emergency care are broad and skipped).
One row per (service, facility); id cz-rpss:<identifikator>-<RUIAN code>. Facilities with a secret address or an end
date are skipped. Dropped: facility manager (`vedouci`), statutory persons, e-mails, mobile numbers (Czech 6xx/7xx).
Location: keyless CUZK RUIAN address points by `kodAdresnihoMista` (cache tools/czech_rpss_scratch/ruian_cache.jsonl).
Residential forms (`pob`: homes, sheltered housing, weekly day care, respite stays) are people's homes, so they are shown at
town level: address = "PSC Town", pin = the town centre from Nominatim (1 req/s, cache geocode_cache.jsonl).
Output: new_resources_czech_rpss.json   Raw: tools/czech_rpss_scratch/rpss.json (+ two code lists)
"""
import collections
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "czech_rpss_scratch")
BASE = "https://data.mpsv.cz/od/soubory/"
FILES = {"rpss.json": BASE + "rpss/rpss.json",
         "cilove-skupiny-osoby.json": BASE + "ciselniky/cilove-skupiny-osoby.json",
         "druhy-socialni-sluzby.json": BASE + "ciselniky/druhy-socialni-sluzby.json"}
RUIAN = "https://ags.cuzk.cz/arcgis/rest/services/RUIAN/Prohlizeci_sluzba_nad_daty_RUIAN/MapServer/1/query"
SRC = "Czech Republic RPSS register of social service providers (MPSV, data.mpsv.cz)"
DIS_GROUPS = {f"CilovaSkupinaOsoby/{i}" for i in (12, 13, 14, 15, 16, 17, 18, 31)}
GROUP_EN = {"12": "other health disability", "13": "combined disability", "14": "intellectual disability", "15": "physical disability",
            "16": "hearing impairment", "17": "health disability", "18": "visual impairment", "31": "autism spectrum"}
DIS_TYPES = {f"DruhSocialniSluzby/{i}" for i in (3, 6, 12, 15, 17, 19, 30)}
ELDERLY = re.compile(r"senior|pečovatelsk|zvláštním režimem|tísňov|nouz|aktivizační služby pro sen", re.I)
# (czech name keyword, English service label, resource type)
LABELS = [("osobní asistence", "Personal assistance", "general_support"), ("odlehčovac", "Respite care", "general_support"),
          ("denní stacionář", "Day care", "general_support"), ("týdenní stacionář", "Weekly day care", "general_support"),
          ("chráněné bydlení", "Supported living", "general_support"), ("domovy pro osoby", "Residential home", "general_support"),
          ("odborné sociální poradenství", "Counselling", "general_support"), ("sociální rehabilitace", "Social rehabilitation", "therapy"),
          ("terapeutické dílny", "Social-therapy workshop", "therapy"), ("raná péče", "Early intervention", "therapy"),
          ("tlumočnick", "Interpreting", "general_support"), ("průvodcovsk", "Guide and reader service", "general_support"),
          ("sociálně aktivizační služby pro rodiny", "Activation service for families", "general_support"),
          ("podpora samostatného bydlení", "Independent-living support", "general_support"),
          ("služby následné péče", "Aftercare", "general_support"), ("terénní", "Outreach service", "general_support")]


def label(czech):
    for kw, en, typ in LABELS:
        if kw in czech.lower():
            return en, typ
    return "Social service", "general_support"


def code_names(fname):
    return {i["id"]: i["nazev"]["cs"] for i in json.load(open(os.path.join(SCRATCH, fname)))["polozky"]}


def fetch_all():
    os.makedirs(SCRATCH, exist_ok=True)
    for f, u in FILES.items():
        if not os.path.exists(os.path.join(SCRATCH, f)):
            rc.download(u, os.path.join(SCRATCH, f), timeout=600)


class Ruian:
    def __init__(self, path):
        self.path, self.cache = path, {}
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                d = json.loads(line)
                self.cache[d["k"]] = d["v"]

    def fill(self, codes):
        todo = sorted(c for c in set(codes) if str(c) not in self.cache)
        with open(self.path, "a", encoding="utf-8") as f:
            for i in range(0, len(todo), 100):
                chunk = todo[i:i + 100]
                q = urllib.parse.urlencode({"where": "kod in (" + ",".join(map(str, chunk)) + ")", "outFields": "kod,adresa",
                                            "returnGeometry": "true", "outSR": 4326, "f": "json"})
                try:
                    d = json.loads(rc.get(RUIAN + "?" + q, delay=0.3, timeout=60))
                except Exception as e:  # noqa: BLE001
                    rc.note_failure("ruian", repr(e))
                    continue  # not cached: retried next run
                got = {}
                for ft in d.get("features", []):
                    got[str(ft["attributes"]["kod"])] = [ft["geometry"]["y"], ft["geometry"]["x"], ft["attributes"].get("adresa") or ""]
                for c in chunk:
                    v = got.get(str(c))  # None = code no longer exists in RUIAN
                    self.cache[str(c)] = v
                    f.write(json.dumps({"k": str(c), "v": v}) + "\n")

    def get(self, code):
        return self.cache.get(str(code))


def landline(items):
    for t in items or []:
        d = re.sub(r"\D", "", (t.get("telefon") or "").replace("+420", "").replace("00420", ""))
        if len(d) == 9 and d[0] in "2345":
            return re.sub(r"\s+", " ", t["telefon"].strip())
    return None


def main():
    fetch_all()
    rc.STATUS["input"] = "MPSV RPSS rpss.json"
    cs, ds = code_names("cilove-skupiny-osoby.json"), code_names("druhy-socialni-sluzby.json")
    items = [x for x in json.load(open(os.path.join(SCRATCH, "rpss.json")))["polozky"] if not x.get("datumPoskytovaniDo")]
    core = []
    for x in items:
        g = {c["cilovaSkupina"]["id"] for c in x["ciloveSkupiny"] or []}
        t = x["druhSocialniSluzby"]["id"]
        if t in DIS_TYPES or (g & DIS_GROUPS and not ELDERLY.search(ds.get(t, ""))):
            core.append((x, g))
    ruian = Ruian(os.path.join(SCRATCH, "ruian_cache.jsonl"))
    ruian.fill(z["adresa"]["kodAdresnihoMista"] for x, _ in core for z in x["zarizeni"] or []
               if z.get("adresa") and z["adresa"].get("kodAdresnihoMista") and not z.get("utajenaAdresa") and not z.get("poskytujeDo"))
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="cz")
    out, skip = [], collections.Counter()
    for x, g in core:
        czech = ds.get(x["druhSocialniSluzby"]["id"], "")
        lab, typ = label(czech)
        residential = any((f.get("forma") or {}).get("id") == "FormaSocialniSluzby/pob" for f in x["formy"] or [])
        grp = [GROUP_EN[i.split("/")[1]] for i in sorted(g & DIS_GROUPS, key=lambda s: int(s.split("/")[1])) if i.split("/")[1] in GROUP_EN]
        autism = "CilovaSkupinaOsoby/31" in g
        prov = x["poskytovatel"]
        web = next((w["web"] for w in x["weby"] or [] if w.get("web")), None)
        web = rc.clean_url(web if web and web.lower().startswith("http") else ("http://" + web if web else "")) if web else None
        phone = landline(x["telefony"])
        for z in x["zarizeni"] or []:
            a = z.get("adresa")
            if z.get("utajenaAdresa"):
                skip["secret address"] += 1
                continue
            if z.get("poskytujeDo"):
                skip["facility ended"] += 1
                continue
            code = a and a.get("kodAdresnihoMista")
            r = ruian.get(code) if code else None
            if not r or not rc.plausible("CZ", r[0], r[1]):
                skip["no RUIAN point"] += 1
                continue
            m = re.search(r",\s*(\d{3}\s?\d{2}\s+.+)$", r[2])
            town = m.group(1).strip() if m else None
            if residential:
                hit = geoc.geocode(f"{town}, Česko") if town else None
                if not hit or not rc.plausible("CZ", *hit):
                    skip["no town centre"] += 1
                    continue
                lat, lng, addr = hit[0], hit[1], f"{town}, Czech Republic"
            else:
                lat, lng, addr = r[0], r[1], f"{r[2]}, Czech Republic"
            fname = rc.clean(z.get("nazev") or prov.get("nazev") or "")
            if not fname:
                skip["no name"] += 1
                continue
            name = fname if lab.lower() in fname.lower() else f"{fname} ({lab})"
            desc = f"Registered social service ({czech}) for people with: {', '.join(grp) or 'disability'}" + \
                   f"; provider {rc.clean(prov.get('nazev') or '')}."
            out.append(rc.entry(name, SRC, typ, [lab, "Social services"], desc, address=addr, phone=phone, website=web,
                                lat=lat, lng=lng, external_id=f"cz-rpss:{x['identifikator']}-{code}", scope=None if autism else "general"))
    print(f"{len(items)} active services; {len(core)} core; {len(out)} rows; skipped {dict(skip)}")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_czech_rpss.json"), out)
    print(collections.Counter(e["type"] for e in fin))
    rc.spot_check(fin, 10, fields=("name", "address", "external_id"))


if __name__ == "__main__":
    main()
