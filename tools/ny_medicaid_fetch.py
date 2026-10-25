#!/usr/bin/env python3
"""
New York Medicaid enrolled-provider listing (health.data.ny.gov dataset keti-qx5t, Socrata, keyless), disability-specific
organisation types only:
    COMMUNITY SUPPORT (OPWDD) 946 · INTERMEDIATE CARE FACILITY (OPWDD) 503 · RESIDENTIAL TREATMENT FACILITY 321
    OPWDD STATE-OPERATED CLINIC 94 · EARLY INTERVENTION OR SCHOOL SUPPORTIVE 3,630   (counts of 2026-10-25)
Never built: LICENSED BEHAVIOR ANALYST (6,404 rows, individuals named by personal name) and every other profession.
Privacy:
  * Individuals are dropped. Every row with an NPI is checked against the NPI registry (cache npi_type_cache.jsonl; only
    the enumeration type is kept): NPI-1 (individual) rows are dropped. Rows without an NPI are OPWDD agencies by name.
  * ICF and residential-treatment sites are people's homes: shown at town level (address "City, NY", pin = the town centre
    from Nominatim, cache geocode_cache.jsonl). Everything else keeps the street address and the listing's own latitude/longitude.
  * provider_email is never read; only the landline-style `telephone` is kept.
One entry per (provider, street address); the professions found there are merged into the description. Rows whose NPI is
already in the live dataset (npi-registry entries) are skipped, and the merge step dedupes the rest on name + address.
Id: ny-medicaid:<mmis_id>:<zip>:<address slug>, or <mmis_id>:<city> for the town-level sites.
Output: new_resources_ny_medicaid.json   Raw: tools/ny_medicaid_scratch/rows.json
"""
import collections
import glob
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "ny_medicaid_scratch")
SRC = "New York Medicaid enrolled provider listing (health.data.ny.gov), disability-specific provider types"
BASE = "https://health.data.ny.gov/resource/keti-qx5t.json?"
NPI = "https://npiregistry.cms.hhs.gov/api/?version=2.1&number="
PROF = {
    "COMMUNITY SUPPORT (OPWDD)": ("social", "Community support (OPWDD)", ["Information & Support", "Day Programs"], False),
    "INTERMEDIATE CARE FACILITY (OPWDD)": ("social", "Intermediate care facility (OPWDD)", ["Residential & Social Care"], True),
    "RESIDENTIAL TREATMENT FACILITY": ("social", "Residential treatment facility", ["Residential & Social Care"], True),
    "OPWDD STATE-OPERATED CLINIC": ("medical", "OPWDD state-operated clinic", ["Clinics"], False),
    "EARLY INTERVENTION OR SCHOOL SUPPORTIVE": ("therapy", "Early intervention / school supportive services", ["Early Intervention"], False),
}
EXPECT_MIN = {"COMMUNITY SUPPORT (OPWDD)": 800, "INTERMEDIATE CARE FACILITY (OPWDD)": 400, "RESIDENTIAL TREATMENT FACILITY": 250,
              "OPWDD STATE-OPERATED CLINIC": 70, "EARLY INTERVENTION OR SCHOOL SUPPORTIVE": 3000}
COLS = ("mmis_id", "mmis_name", "profession_or_service", "latitude", "longitude", "service_address", "city", "zip_code", "npi", "telephone")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60]


def rows():
    path = os.path.join(SCRATCH, "rows.json")
    if os.path.exists(path):
        return json.load(open(path))
    where = " OR ".join(f"profession_or_service='{p}'" for p in PROF)
    d = rc.get_json(BASE + urllib.parse.urlencode({"$where": where, "$limit": 20000, "$order": ":id"}), timeout=180)
    if not isinstance(d, list) or not d:
        raise RuntimeError(f"NY Medicaid: expected a non-empty list, got {str(d)[:200]}")
    if len(d) >= 20000:
        raise RuntimeError("NY Medicaid: reached $limit=20000; raise it")
    present = set().union(*(r.keys() for r in d))
    missing = [c for c in COLS if c not in present]
    if missing:
        raise RuntimeError(f"NY Medicaid: column(s) {missing} absent from every row -- renamed upstream?")
    count = collections.Counter(r["profession_or_service"] for r in d)
    short = {p: (count[p], m) for p, m in EXPECT_MIN.items() if count[p] < m}
    if short:
        raise RuntimeError(f"NY Medicaid: profession counts below the floor (got, floor): {short}")
    os.makedirs(SCRATCH, exist_ok=True)
    json.dump(d, open(path, "w"))
    return d


class NpiType:
    """NPI enumeration type (NPI-1 individual / NPI-2 organisation), cached; nothing else is stored."""

    def __init__(self, path):
        self.path, self.cache = path, {}
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                d = json.loads(line)
                self.cache[d["n"]] = d["t"]

    def get(self, npi):
        if npi in self.cache:
            return self.cache[npi]
        try:
            d = json.loads(rc.get(NPI + npi, delay=0.1, timeout=30))
        except Exception as e:  # noqa: BLE001
            rc.note_failure("npi", f"{npi}: {e!r}")
            return None   # not cached: retried next run
        r = d.get("results") or []
        t = r[0].get("enumeration_type") if r else "none"
        self.cache[npi] = t
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"n": npi, "t": t}) + "\n")
        return t


def live_npis():
    s = set()
    for f in glob.glob(os.path.join(rc.REPO, "data", "us", "*.json")):
        if f.endswith("manifest.json"):
            continue
        d = json.load(open(f))
        for e in (d.get("entries", d) if isinstance(d, dict) else d):
            if e.get("npi_number"):
                s.add(str(e["npi_number"]))
    return s


def phone(s):
    d = re.sub(r"\D", "", s or "")
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else None


def main():
    data = rows()
    rc.STATUS["input"] = f"NY Medicaid keti-qx5t, {len(data)} rows"
    npi, geoc, have = NpiType(os.path.join(SCRATCH, "npi_type_cache.jsonl")), rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="us"), live_npis()
    groups, skip = collections.OrderedDict(), collections.Counter()
    for r in data:
        prof = r["profession_or_service"]
        if prof not in PROF:
            continue
        n = (r.get("npi") or "").strip()
        if n:
            t = npi.get(n)
            if t is None:
                skip["npi lookup failed"] += 1
                continue
            if t == "NPI-1":
                skip["individual (NPI-1)"] += 1
                continue
            if n in have:
                skip["already in dataset by NPI"] += 1
                continue
        city = rc.clean(r.get("city")).title()
        if not city:
            skip["no city"] += 1
            continue
        town_only = PROF[prof][3]
        street = rc.clean(r.get("service_address")).title()
        key = (r["mmis_id"], city if town_only else f"{street}|{r.get('zip_code')}")
        g = groups.setdefault(key, {"r": r, "profs": [], "town": False})
        g["town"] = g["town"] or town_only
        if prof not in g["profs"]:
            g["profs"].append(prof)
    out = []
    for (mid, _), g in groups.items():
        r, profs = g["r"], g["profs"]
        city, zc = rc.clean(r.get("city")).title(), rc.clean(r.get("zip_code"))[:5]
        street = rc.clean(r.get("service_address")).title()
        if g["town"]:
            hit = geoc.geocode(f"{city}, New York, United States")
            if geoc.last_failed and not hit:
                skip["town lookup failed"] += 1
                continue
            lat, lng = hit if hit else (None, None)
            addr, eid, ph = f"{city}, NY", f"ny-medicaid:{mid}:{slug(city)}", None   # a home's phone is not published
        else:
            try:
                lat, lng = float(r["latitude"]), float(r["longitude"])
            except Exception:  # noqa: BLE001
                skip["no coordinates"] += 1
                continue
            addr = ", ".join(x for x in (street, city, f"NY {zc}" if zc else "NY") if x)
            eid, ph = f"ny-medicaid:{mid}:{zc}:{slug(street)}", phone(r.get("telephone"))
        if lat is None or not rc.plausible("US", lat, lng):
            skip["implausible/no location"] += 1
            continue
        typ = PROF[profs[0]][0]
        kinds = [PROF[p][1] for p in profs]
        svc = list(dict.fromkeys(s for p in profs for s in PROF[p][2]))
        name = rc.clean(r["mmis_name"])
        name = name.title() if name.isupper() else name
        out.append(rc.entry(name, SRC, typ, svc, "New York Medicaid-enrolled provider: " + "; ".join(kinds).lower() + ".",
                            address=addr, phone=ph, lat=lat, lng=lng, external_id=eid, scope="general"))
    print(f"{len(groups)} provider-sites; {len(out)} built; skipped {dict(skip)}")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_ny_medicaid.json"), out)
    print(collections.Counter(e["type"] for e in fin))
    rc.spot_check(fin, 15, fields=("name", "address", "external_id"))


if __name__ == "__main__":
    main()
