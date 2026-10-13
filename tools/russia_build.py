#!/usr/bin/env python3
"""
Russia: builds new_resources_russia.json (resource-schema entries) from the raw scratch files the
russia_*_fetch.py scripts wrote into tools/russia_scratch/. Run the fetchers first:

    python3 tools/russia_frc_fetch.py
    python3 tools/russia_zhitvmeste_fetch.py
    python3 tools/russia_misc_fetch.py
    python3 tools/russia_build.py            # geocodes via Nominatim (1 req/s, cached, resumable)
    python3 tools/merge_new_resources.py && python3 tools/split_by_region.py

Sources (all official, keyless; details in HANDOFF.md "Russia"):
  R1  autism-frc.ru national navigator      all entries are autism-relevant (no disability_scope)
  R2  zhit-vmeste.ru accessibility map      rehab/residential/children's homes, disability-assessment
                                            bureaus (MSE), inclusive children's camps (have coordinates)
  R3  Ministry of Justice NGO register      disability-related active NGOs (OGRN id; region only)
  R5  VOG branches, national NGOs, SONKO    small lists with street addresses

The broad КЦСОН/ЦСОН tier of R2 (complex social-service centres that mostly serve elderly people) is
included with `breadth: "broad"` -- the dataset's first broad tier; the app has no filter for it yet.

Rules carried from the research note: dedupe on OGRN where there is one, otherwise on (normalised name,
region) -- never name alone; drop all personal names (chairs, directors); guard Russian false positives
("глух" inside "глухарь", addiction rehab, elderly-only homes, ...).
"""
import csv
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "russia_scratch")
OUT_PATH = os.path.join(REPO, "new_resources_russia.json")
GEO_CACHE = os.path.join(SCRATCH, "geocode_cache.jsonl")
UA = "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SRC_FRC = "Russia Federal Resource Centre for ASD national navigator of autism organisations (autism-frc.ru), Ministry of Education"
SRC_ZV = "Russia Ministry of Labour accessible-environment map (zhit-vmeste.ru) - official portal"
SRC_MINJUST = "Russia Ministry of Justice register of NGOs providing socially useful services (data.gov.ru)"
SRC_VOG = "Russian Society of the Deaf (VOG) regional branches - official site (voginfo.ru)"
SRC_ZVNGO = "Russia Ministry of Labour accessible-environment portal: all-Russian disability organisations (zhit-vmeste.ru)"
SRC_SONKO = "Russia Ministry of Labour register of SONKO support recipients (mintrud.gov.ru open data)"


# ── helpers ──────────────────────────────────────────────────────────────────────────────────
def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»“”„\"'`\\]", "", s)
    s = re.sub(r"\b(ано|нко|гбу|гау|гку|гбоу|мбоу|маоу|мбдоу|коу|гоу|гаусо|гбусо|кгбсусо|асусон|фку|ооо|роо|моо|ооио?|бф)\b", "", s)
    for long in ("автономная некоммерческая организация", "государственное бюджетное учреждение",
                 "региональная общественная организация", "благотворительный фонд"):
        s = s.replace(long, "")
    return "".join(c for c in s if c.isalnum())


def with_russia(addr, region):
    a = clean(addr)
    if region and region.lower().replace("республика ", "") not in a.lower():
        a = f"{a}, {region}" if a else region
    return a if re.search(r"росси", a, re.I) else f"{a}, Россия"


# Disability / autism name guards (Cyrillic, case-insensitive). Word-form lists, not bare stems:
# bare "глух" would hit "глухарь" (capercaillie) in hunting datasets.
DISABILITY_RE = re.compile(
    r"инвалид|\bове?з\b|ограниченн\w+ возможност|аутизм|\bрас\b|синдром\w* даун|\bдцп\b|церебральн|"
    r"умственн\w* отсталост|интеллектуальн\w* наруш|ментальн\w* наруш|ментальн\w* инвалид|"
    r"глух(?:их|ой|ие|ого|ому|ая|им|ими)\b|слабослышащ|слепых|слабовидящ|незрячих|по зрению|"
    r"реабилитац\w* и абилитац|абилитац|коррекционн|логопед|сурдо|тифло|ранн\w+ помощ", re.I)
NOT_DISABILITY_RE = re.compile(
    r"нарко|алкогол|зависим|глухар|ресоциализац|для одиноких престарел|боев\w+ действий и военной службы",
    re.I)
# R3 services-text codes that mean services *for disabled people* (5.x rehab, 4.7/4.8 employment,
# 14 education of elderly & disabled, 19.2/19.3 adapted sport).
R3_CODE_RE = re.compile(r"(?:^|, )(?:5\.[1-6]|4\.[78]|14|19\.[23])\. ")


def disability_text(text):
    return bool(DISABILITY_RE.search(text)) and not NOT_DISABILITY_RE.search(text)


# ── geocoding (Nominatim, cached on disk, resumable) ─────────────────────────────────────────
_cache = {}
if os.path.exists(GEO_CACHE):
    for line in open(GEO_CACHE, encoding="utf-8"):
        try:
            d = json.loads(line)
            _cache[d["q"]] = d["c"]
        except Exception:  # noqa: BLE001
            pass
_last = [0.0]


def geocode(q):
    """(lat, lng) or None. 1 request/second, results (including misses) cached."""
    if q in _cache:
        c = _cache[q]
        return tuple(c) if c else None
    wait = 1.05 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    url = NOMINATIM + "?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1, "countrycodes": "ru,ua,by,kz"})
    res = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                data = json.loads(r.read())
            res = [float(data[0]["lat"]), float(data[0]["lon"])] if data else None
            break
        except Exception:  # noqa: BLE001
            time.sleep(3 * (attempt + 1))
    _last[0] = time.time()
    _cache[q] = res
    with open(GEO_CACHE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"q": q, "c": res}, ensure_ascii=False) + "\n")
    return tuple(res) if res else None


_NL = r"(?![а-яё])"   # abbreviation must not be the start of a longer word ("ул" vs "улица")
STREET_WORD_RE = re.compile(
    r"^(?:ул|улица|пр-т|пр|просп|проспект|пер|переулок|ш|шоссе|бул|бульвар|наб|набережная|пл|площадь|тракт|"
    r"мкр|микрорайон|проезд|аллея|тупик)" + _NL + r"\.?|(?:улица|ул|проспект|пр-т|переулок|пер|шоссе|ш|бульвар|бул|набережная|наб|площадь|пл|тракт|проезд)\.?$", re.I)
STREET_ABBR = [(r"\bул" + _NL + r"\.?\s*", "улица "), (r"\bпр-т" + _NL + r"\.?\s*", "проспект "), (r"\bпросп" + _NL + r"\.?\s*", "проспект "),
               (r"\bпер" + _NL + r"\.?\s+", "переулок "), (r"\bбул" + _NL + r"\.?\s*", "бульвар "), (r"\bнаб" + _NL + r"\.?\s*", "набережная "),
               (r"\bш" + _NL + r"\.\s*", "шоссе "), (r"\bпл" + _NL + r"\.?\s*", "площадь "), (r"\bмкр" + _NL + r"\.?\s*", "микрорайон ")]
LOCALITY_PREFIX_RE = re.compile(r"^(?:город|деревня|поселок|посёлок|станица|хутор|село|аул|пгт|р\.?\s?п|рп|пос|г|с|ст|п|д|х)" + _NL + r"\.?\s*", re.I)
JUNK_PART_RE = re.compile(r"район|р-н|округ|^рф$|россия|област|обл\.|республик|край", re.I)


def _is_index(p):
    return bool(re.fullmatch(r"[A-Za-zА-Яа-я0-9]{5,6}", p)) and sum(c.isdigit() for c in p) >= 3


def address_queries(address, region):
    """Nominatim queries from most to least specific, from a Russian free-text address."""
    a = re.sub(r"\b\d{6}\b", " ", clean(address))
    a = re.sub(r"\b(?:офис|оф|помещение|пом|этаж|эт|кв|каб|комн)" + _NL + r"\.?\s*[\w/\-]+", " ", a, flags=re.I)
    a = re.sub(r"\b(?:корпус|корп|строение|стр|литера|литер)" + _NL + r"\.?\s*[\w/\-]+", " ", a, flags=re.I)
    parts = [p.strip(" .;") for p in re.split(r"[,;]", a) if p.strip(" .;")]
    street = number = marked = unmarked = None
    for pl in parts:
        if _is_index(pl):
            continue
        if STREET_WORD_RE.search(pl) and not street:
            m = re.match(r"^(.*?)[\s,]*(?:д\.?|дом)?\s*№?\s*(\d+[\w/\-]*)\s*$", pl)
            street, number = (m.group(1), m.group(2)) if m and m.group(1) else (pl, None)
            continue
        m = re.match(r"^(?:д\.?|дом)\s*№?\s*(\d.*)$", pl, re.I)
        if m and not number:
            number = m.group(1)
            continue
        if re.match(r"^\d+[\w/\-]*$", pl) and not number:
            number = pl
            continue
        if LOCALITY_PREFIX_RE.match(pl) and not JUNK_PART_RE.search(pl):
            marked = LOCALITY_PREFIX_RE.sub("", pl).strip()
        elif not JUNK_PART_RE.search(pl) and not unmarked and not re.match(r"^\d", pl):
            unmarked = pl
    locality = marked or (unmarked if not street else None)
    if street:
        for pat, rep in STREET_ABBR:
            street = re.sub(pat, rep, street, flags=re.I)
        street = re.sub(r"\s+", " ", street).strip(" ,")
    tail = ", ".join(dict.fromkeys(x for x in (locality, region) if x))
    qs = []
    if street and number:
        qs.append(f"{street} {number}, {tail}")
    if street:
        qs.append(f"{street}, {tail}")
    if locality:
        qs.append(tail)
    return [q + ", Россия" for q in dict.fromkeys(qs) if q.strip(", ")]


def locate(address, region):
    """Best-effort coordinates: address queries (street+number -> street -> locality), then the
    region's own centre. Returns (coords, precision) where precision is 'address' or 'region'."""
    for i, q in enumerate(address_queries(address, region) if clean(address) else []):
        c = geocode(q)
        if c:
            return c, "address" if "," in q and i < 2 else "region"
    c = geocode(f"{region}, Россия") if region else None
    return (c, "region") if c else (None, None)


# ── R1: FRC autism navigator ─────────────────────────────────────────────────────────────────
SECTOR_TYPE = {"education": ("education", ["Special Education", "Autism Support"]),
               "health": ("medical", ["Health Care", "Autism Support"]),
               "social_protection": ("general_support", ["Social Services", "Autism Support"]),
               "culture": ("social", ["Culture & Recreation", "Autism Support"]),
               "sport": ("social", ["Sport & Recreation", "Autism Support"])}


def build_frc():
    rows = json.load(open(os.path.join(SCRATCH, "frc.json"), encoding="utf-8"))
    out = []
    for r in rows:
        sector = r.get("sector")
        if sector in SECTOR_TYPE:
            typ, services = SECTOR_TYPE[sector]
        elif r.get("org_type") in ("ngo", "charitable_foundation"):
            typ, services = "advocacy", ["Advocacy", "Autism Support"]
        else:
            typ, services = "general_support", ["Information & Support", "Autism Support"]
        region = r.get("region", "")
        coords, prec = locate(r["address"], region)
        e = {"name": r["name"], "address": with_russia(r["address"], region) if prec == "address" else f"{region}, Россия",
             "phone": r["phone"], "website": r["website"], "type": typ, "source": SRC_FRC, "services": services,
             "description": (f"Listed in the Russian Federal Resource Centre for ASD's national navigator of "
                             f"organisations that help children with autism ({region})."),
             "external_id": f"frc:{r['id']}", "breadth": "core"}
        if coords:
            e["coordinates"] = {"lat": coords[0], "lng": coords[1]}
        else:
            e["placeless"] = True
        out.append(e)
        if len(out) % 100 == 0:
            print(f"  R1 {len(out)}/{len(rows)}", flush=True)
    return out


# ── R2: zhit-vmeste accessibility map ────────────────────────────────────────────────────────
ZV_CORE_RE = re.compile(
    r"реабилит|абилит|психоневрологическ|дом-интернат|интернат для|\bддi?\b|детей-инвалид|детей с огр|"
    r"инвалид|сопровождаем\w* прожив|ранн\w+ помощ|помощи детям|\bсрцн\b|социально-реабилитацион|"
    r"аутизм|\bрас\b|\bпни\b|\bпнд\b|для несовершеннолетних", re.I)
ZV_EXCLUDE_RE = re.compile(
    r"управлен|министерств|отдел социальн|занятост|пенсион|\bпфр\b|\bфсс\b|\bсфр\b|администрац|комитет|"
    r"наркоман|алкогол|пансионат для ветеран|ветеранов", re.I)
# Elderly-only homes are out; "for the elderly and disabled" homes are in (the disabled half is the point).
ZV_ELDERLY_ONLY_RE = re.compile(r"престарел|одиноких", re.I)
ZV_BUILDING_RE = re.compile(r"\b(?:строение|корпус|здание|литер[а]?|помещение|отделение)\b|\bстр\.|\bкорп\.", re.I)
ZV_BROAD_RE = re.compile(r"кцсо|\bцсо\b|комплексный центр социального|территориальный центр социального", re.I)


def build_zv():
    rows = json.load(open(os.path.join(SCRATCH, "zv.json"), encoding="utf-8"))
    out, seen = [], set()
    stats = {"mse": 0, "inclusive_recreation": 0, "core": 0, "broad": 0, "excluded": 0, "building_skipped": 0, "other": 0}
    for r in rows:
        name, kind = r["name"], r["kind"]
        broad = False
        if kind == "social_protection":
            if ZV_BROAD_RE.search(name):
                stats["broad"] += 1
                broad = True
            elif ZV_EXCLUDE_RE.search(name) or NOT_DISABILITY_RE.search(name):
                stats["excluded"] += 1
                continue
            elif not ZV_CORE_RE.search(name) or (ZV_ELDERLY_ONLY_RE.search(name) and not re.search(r"инвалид|психоневр", name, re.I)):
                stats["other"] += 1
                continue
            elif ZV_BUILDING_RE.search(name):
                stats["building_skipped"] += 1
                continue
        key = (kind, norm(name), r["region_id"])
        if key in seen:
            continue
        seen.add(key)
        if kind == "mse":
            typ, services, desc = "medical", ["Disability Assessment (MSE)", "Information & Support"], \
                "State medical-social expertise bureau that assesses disability status and individual rehabilitation needs."
            stats["mse"] += 1
        elif kind == "inclusive_recreation":
            typ, services, desc = "social", ["Inclusive Children's Recreation", "Summer Camp"], \
                "Listed on the Russian Ministry of Labour accessible-environment map as inclusive children's recreation."
            stats["inclusive_recreation"] += 1
        elif broad:
            typ, services = "general_support", ["Social Services", "Information & Support"]
            desc = "Complex social-service centre listed on the Russian Ministry of Labour accessible-environment map; serves elderly people, families and people with disabilities (broad tier)."
            stats["broad_added"] = stats.get("broad_added", 0) + 1
        else:
            n = name.lower()
            if re.search(r"реабилит|абилит|ранн\w+ помощ", n) and not re.search(r"интернат", n):
                typ, services = "therapy", ["Rehabilitation", "Habilitation"]
            else:
                typ, services = "general_support", ["Residential & Social Care", "Information & Support"]
            desc = "Disability rehabilitation / residential social-care institution listed on the Russian Ministry of Labour accessible-environment map."
            stats["core"] += 1
        out.append({"name": name, "address": f"{r['region']}, Россия", "type": typ, "source": SRC_ZV,
                    "services": services, "description": desc, "website": "",
                    "coordinates": {"lat": round(r["lat"], 6), "lng": round(r["lon"], 6)},
                    "external_id": f"zv:{kind}:{r['id']}", "breadth": "broad" if broad else "core", "disability_scope": "general"})
    print("  R2 stats:", stats)
    return out


# ── R3: Ministry of Justice register ─────────────────────────────────────────────────────────
def r3_type(services):
    if re.search(r"(?:^|, )5\.", services):
        return "therapy", ["Rehabilitation", "Habilitation"]
    if re.search(r"(?:^|, )(?:12|13)\.", services):
        return "education", ["Education", "Advocacy"]
    if re.search(r"(?:^|, )(?:10|19)\.", services):
        return "social", ["Sport & Recreation", "Advocacy"]
    if re.search(r"(?:^|, )(?:[123]\.|4\.[78])", services):
        return "general_support", ["Social Services", "Information & Support"]
    return "advocacy", ["Advocacy", "Information & Support"]


def build_minjust():
    out, by_ogrn = [], {}
    with open(os.path.join(SCRATCH, "minjust_opu.csv"), encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f, delimiter=";"):
            if len(row) < 9 or row[8].strip() != "Зарегистрированные":
                continue
            name, ogrn, _, services, _, _, _, region, _ = [c.strip() for c in row[:9]]
            if not (disability_text(name) or R3_CODE_RE.search(services) or disability_text(services)):
                continue
            if NOT_DISABILITY_RE.search(name):
                continue
            by_ogrn.setdefault(ogrn or norm(name) + norm(region), (name, services, region, ogrn))
    for key, (name, services, region, ogrn) in by_ogrn.items():
        typ, svc = r3_type(services)
        coords = geocode(f"{region}, Россия")
        e = {"name": re.sub(r"\s+", " ", name), "address": f"{region}, Россия", "type": typ, "source": SRC_MINJUST,
             "services": svc, "website": "",
             "description": "NGO on the Russian Ministry of Justice register of organisations providing socially useful services to disabled people (located by region only).",
             "external_id": f"ogrn:{ogrn}" if ogrn else f"minjust:{key}", "breadth": "core", "disability_scope": "general"}
        if coords:
            e["coordinates"] = {"lat": coords[0], "lng": coords[1]}
        else:
            e["placeless"] = True
        out.append(e)
    print(f"  R3: {len(out)} disability-related active NGOs")
    return out


# ── R5: VOG branches, national NGOs, SONKO ───────────────────────────────────────────────────
def build_vog():
    h = open(os.path.join(SCRATCH, "vog.html"), encoding="utf-8").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    lines = [re.sub(r"\s+", " ", l).strip() for l in t.split("\n")]
    lines = [l for l in lines if l]
    start = lines.index("Региональные отделения", lines.index("Региональные отделения") + 1)
    out, i, region = [], start + 1, ""
    while i < len(lines):
        l = lines[i]
        if l.startswith("Председатель"):
            i += 1
            continue
        if "Всероссийское общество глухих" in l and re.search(r"отделение|организация", l, re.I) and i + 1 < len(lines):
            name, addr = l, lines[i + 1]
            phone, site = "", ""
            j = i + 2
            while j < len(lines) and not lines[j].startswith("Региональное отделение на карте"):
                if lines[j].startswith("Код") or lines[j].startswith("Тел"):
                    phone = lines[j]
                if lines[j].startswith("http"):
                    site = lines[j]
                j += 1
            phone = re.sub(r"^Код\s*", "", phone)
            coords, prec = locate(addr, region)
            e = {"name": name, "address": with_russia(addr, ""), "phone": phone, "website": site, "type": "advocacy",
                 "source": SRC_VOG, "services": ["Advocacy", "Deaf Community Support"],
                 "description": "Regional branch of the All-Russian Society of the Deaf (VOG).",
                 "external_id": "vog:" + norm(name)[:80], "breadth": "core", "disability_scope": "general"}
            if coords:
                e["coordinates"] = {"lat": coords[0], "lng": coords[1]}
            else:
                e["placeless"] = True
            out.append(e)
            i = j
        else:
            if re.match(r"^(Республика|.*(край|область|округ)|Москва|Санкт-Петербург|Севастополь)\b", l) and len(l) < 60 and "отделение" not in l:
                region = l
            i += 1
    print(f"  VOG branches: {len(out)}")
    return out


def build_zv_ngo():
    h = open(os.path.join(SCRATCH, "zv_ngo.html"), encoding="utf-8").read()
    out = []
    for block in h.split('<div class="oo_flex">')[1:]:
        g = lambda cls: clean(re.search(rf'class="{cls}">(.*?)</div>', block, re.S).group(1)) if re.search(rf'class="{cls}">', block) else ""
        name, desc, addr = g("oo_h"), g("oo_t"), g("oo_a")
        phones = [clean(m) for m in re.findall(r"<span>(.*?)</span>", block, re.S)]
        sites = re.findall(r'href="(https?://[^"]+)"', block)
        if not name or not disability_text(name + " " + desc):
            continue
        coords, prec = locate(addr, "Москва")
        e = {"name": name, "address": with_russia(addr, ""), "phone": ", ".join(phones), "website": sites[0] if sites else "",
             "type": "advocacy", "source": SRC_ZVNGO, "services": ["Advocacy", "Information & Support"],
             "description": desc[:400], "external_id": "zvngo:" + norm(name)[:80], "breadth": "core", "disability_scope": "general"}
        if coords:
            e["coordinates"] = {"lat": coords[0], "lng": coords[1]}
        else:
            e["placeless"] = True
        out.append(e)
    print(f"  national NGOs: {len(out)}")
    return out


def build_sonko():
    out, seen = [], set()
    with open(os.path.join(SCRATCH, "sonko.csv"), encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            name = re.sub(r"\s+", " ", r["name"].replace("\\", "")).strip()
            text = name + " " + r["deyatelnost"]
            if r["ogrn"] in seen or not disability_text(text):
                continue
            seen.add(r["ogrn"])
            coords, prec = locate(r["address"], "")
            e = {"name": name, "address": with_russia(r["address"], ""), "website": "", "type": "advocacy", "source": SRC_SONKO,
                 "services": ["Advocacy", "Information & Support"],
                 "description": "Organisation that received federal Ministry of Labour support for work with disabled people.",
                 "external_id": f"ogrn:{r['ogrn']}", "breadth": "core", "disability_scope": "general"}
            if coords:
                e["coordinates"] = {"lat": coords[0], "lng": coords[1]}
            else:
                e["placeless"] = True
            out.append(e)
    print(f"  SONKO: {len(out)}")
    return out


def main():
    only = set(sys.argv[1:])
    steps = [("zv", build_zv), ("minjust", build_minjust), ("sonko", build_sonko), ("vog", build_vog),
             ("zvngo", build_zv_ngo), ("frc", build_frc)]
    entries = []
    for key, fn in steps:
        if only and key not in only:
            continue
        print(f"Building {key} ...", flush=True)
        entries.extend(fn())
    # drop empty phone/website keys to match the other new_resources files
    for e in entries:
        for k in ("phone", "website"):
            if k in e and not e[k]:
                del e[k]
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    located = sum(1 for e in entries if e.get("coordinates"))
    print(f"Wrote {len(entries)} entries ({located} with coordinates) to {OUT_PATH}")


if __name__ == "__main__":
    main()
