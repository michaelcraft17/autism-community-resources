#!/usr/bin/env python3
"""
Latvia -- Ministry of Welfare (LM) register of social-service providers, data.gov.lv (CC0, refreshed daily).

CKAN: https://data.gov.lv/dati/api/3/action/package_show?id=socialo-pakalpojumu-sniedzeju-registra-dati
The file name carries the date, so the URL is resolved through package_show. Keyless.

Selection: StatusaKods == 1 (provider is providing the service) and a client group for disability
(02 intellectual/mental, 06 vision, 07 hearing, 08 physical, 16 adults unable to self-care). One entry per
(RegistracijasNumurs, address); several services at one address are merged into one entry.
The other active locations (elderly, crisis, families; 'broad' in the round-6 notes) are not disability-specific
and are not merged.

Privacy (build rules): group houses / group apartments / half-way houses (grupu maja/dzivoklis, pusceļa maja) are
people's homes: not pinned at their address, one entry per provider and municipality at the town centre.
PakalpojumaVaditajs (the manager's name), e-mail and sole traders (Individuālais komersants, Privātuzņēmējs) are never used.

Geocoding: Nominatim (1 req/s, cached) on the full address; addresses it cannot place are dropped.
Output: new_resources_latvia_lm.json
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "latvia_scratch")
SOURCE = "Latvia Ministry of Welfare social-service provider register (data.gov.lv)"
CKAN = "https://data.gov.lv/dati/api/3/action/package_show?id=socialo-pakalpojumu-sniedzeju-registra-dati"
DISABILITY_GROUPS = {"02", "06", "07", "08", "16"}
HOME_RE = re.compile(r"grupu (māja|mājas|dzīvoklis|dzivoklis)|grupu dz|pusceļa", re.I)
SOLE_TRADER = re.compile(r"Individuālais komersants|Privātuzņēmējs", re.I)


def variants(adr):
    """Nominatim copes badly with the register's 'street, parish, municipality nov., LV-1234' form: drop the postcode and
    administrative parts, try 'street, town', then the town alone (a town-level pin for a rural address)."""
    parts = [p.strip() for p in adr.split(",") if p.strip()]
    parts = [p for p in parts if not p.upper().startswith("LV-")]
    place = [p for p in parts[1:] if not re.search(r"\b(nov\.|novads|pag\.|pagasts)\s*$", p, re.I)]
    street = re.sub(r"^\"|\"$", "", parts[0]) if parts else ""
    town = place[-1] if place else (parts[-1] if parts else "")
    out = []
    if street and town:
        out.append((f"{street}, {town}, Latvia", False))
    if town:
        out.append((f"{town}, Latvia", True))
    return out


def classify(svc):
    s = svc.lower()
    if "dienas" in s or "darbnīc" in s or "darbnic" in s or "sociālā darba" in s or "kopienā" in s:
        return "social", ["Day Programs"] if ("dienas" in s or "darbn" in s) else ["Information & Support"]
    if "rehabilit" in s:
        return "therapy", ["Rehabilitation"]
    if "atelp" in s:
        return "social", ["Respite Care"]
    if "aprūpe" in s or "aprupe" in s or "pansija" in s:
        return "social", ["Residential & Social Care"]
    return "general_support", ["Information & Support"]


def main():
    os.makedirs(SCRATCH, exist_ok=True)
    path = os.path.join(SCRATCH, "data.json")
    if not os.path.exists(path):
        pkg = rc.get_json(CKAN)["result"]
        url = next(r["url"] for r in pkg["resources"] if "metadata" not in r["url"] and r["url"].endswith(".json"))
        rc.download(url, path)
    rows = json.load(open(path, encoding="utf-8"))["data"]
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="lv")
    groups, homes = {}, {}
    for r in rows:
        if r.get("StatusaKods") != 1:
            continue
        if not any(g.get("KlientuGrupasKods") in DISABILITY_GROUPS for g in r.get("KlientuGrupas") or []):
            continue
        if SOLE_TRADER.search(r.get("JuridiskaisStatuss") or ""):
            continue
        adr = rc.clean((r.get("FaktiskaAdrese") or {}).get("Adrese") or (r.get("JuridiskaAdrese") or {}).get("Adrese"))
        if not adr:
            continue
        svc = rc.clean(r.get("SniedzamaPakalpojumaNosaukums"))
        parts = [p.strip() for p in adr.split(",")]
        town = parts[-2] if len(parts) >= 3 and parts[-1].upper().startswith("LV-") else parts[-1]
        if HOME_RE.search(svc):
            key = (r["RegistracijasNumurs"], town)
            h = homes.setdefault(key, {"name": rc.clean(r["PakalpojumaSniedzejaNosaukums"]), "town": town, "n": 0})
            h["n"] += 1
            continue
        key = (r["RegistracijasNumurs"], adr)
        g = groups.setdefault(key, {"name": rc.clean(r["PakalpojumaSniedzejaNosaukums"]), "adr": adr, "svcs": [], "r": r})
        if svc not in g["svcs"]:
            g["svcs"].append(svc)
    entries = []
    nogeo = town_level = 0
    for (reg, adr), g in groups.items():
        hit, approx = None, False
        for q, approx in variants(adr):
            hit = geoc.geocode(q)
            if hit and rc.plausible("LV", hit[0], hit[1]):
                break
            hit = None
        if not hit:
            nogeo += 1
            continue
        town_level += approx
        ci = g["r"].get("KontaktInformacija") or {}
        phone = rc.clean(ci.get("Talrunis"))
        if phone and not phone.startswith("+"):
            phone = "+371 " + phone
        web = next((w.get("MajasLapa") for w in ci.get("MajasLapas") or [] if w.get("MajasLapa")), None)
        typ, services = classify(g["svcs"][0])
        for s in g["svcs"][1:]:
            for x in classify(s)[1]:
                if x not in services:
                    services.append(x)
        entries.append(rc.entry(g["name"], SOURCE, typ, services,
                                f"{'; '.join(g['svcs'])}. Registered social-service provider for people with disabilities.",
                                address=adr + ", Latvia", phone=phone or None, website=rc.clean_url(web), lat=hit[0], lng=hit[1],
                                external_id=f"lv-sp:{reg}:{re.sub(r'[^0-9a-zāčēģīķļņšūž]+', '', adr.lower())[:40]}",
                                scope="general"))
    nohome = 0
    for (reg, town), h in homes.items():
        hit = geoc.geocode(f"{town}, Latvia")
        if not hit or not rc.plausible("LV", hit[0], hit[1]):
            nohome += 1
            continue
        n = f"{h['n']} group homes/apartments" if h["n"] > 1 else "group home/apartment"
        entries.append(rc.entry(f"{h['name']} - group housing, {town}", SOURCE, "social", ["Residential & Social Care"],
                                f"Group housing for people with disabilities ({n}) run by {h['name']} in {town}. Shown at town level; individual homes are not published here.",
                                address=f"{town}, Latvia", lat=hit[0], lng=hit[1], external_id=f"lv-housing:{reg}:{re.sub(r'[^0-9a-z]+', '', town.lower())}",
                                scope="general"))
    print(f"{len(groups)} service locations ({nogeo} without a geocode, {town_level} placed at town level), {sum(h['n'] for h in homes.values())} housing locations -> {len(homes)} town entries ({nohome} without a geocode)")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_latvia_lm.json"), entries)
    rc.spot_check(out, 30, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
