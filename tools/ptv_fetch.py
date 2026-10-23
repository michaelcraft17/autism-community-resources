#!/usr/bin/env python3
"""
Finland: disability service locations from PTV (Palvelutietovaranto / Suomi.fi service catalogue) API v11, keyless:

    https://api.palvelutietovaranto.suomi.fi/api/v11
      Service/serviceClass?uri=<ptvserclass2 URI>&page=N     candidate service ids (imprecise -- re-checked below)
      Service/targetGroup?uri=<ptvkohderyhmat URI>&page=N
      Service/list?guids=<<=50 ids>                          service detail (own serviceClasses, targetGroups, channels)
      ServiceChannel/list?guids=<<=50 ids>                   channel detail (ServiceLocation: address + WGS84 coordinates)
      Organization/list?guids=<<=50 ids>                     operator names

Core service = its own serviceClasses include P4.4 (Vammaispalvelut), P4.5 (henkilokohtainen apu) or P4.7
(Kehitysvammahuolto), or its name matches the disability regex from the source notes. Broad = other services tagged
target group KR1.6 (Vammaiset) -> new_resources_ptv_broad.json. ServiceLocation channels only; generic citizen-service
points (Kela, suomi-piste, library, health centre, town hall ...) are dropped.

Privacy: group homes / housing units (ryhmakoti, asumisyksikko, asumispalvelu, palveluasuminen ...) are people's
homes. They are NOT pinned at their address: one entry per operator and municipality, located at the municipality
centre (the coordinates the dataset already holds for that entry, rc.prior_coords, else Nominatim, cached) and named
after the operator. Day-activity centres, offices and similar stay pinned at PTV's own coordinates; a location without
them is dropped, never geocoded.
Contact-person names inside descriptions are never copied (descriptions are not copied at all).

Writes new_resources_ptv.json and new_resources_ptv_broad.json.
"""
import json
import os
import re
import sys

from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "ptv_scratch")
B = "https://api.palvelutietovaranto.suomi.fi/api/v11"
SOURCE = "Finland PTV Suomi.fi service catalogue (Digital and Population Data Services Agency) - open data"
CORE_CLASSES = {"P4.4", "P4.5", "P4.7"}
CLASS_URIS = [f"http://uri.suomi.fi/codelist/ptv/ptvserclass2/code/{c}" for c in sorted(CORE_CLASSES)]
TARGET_URI = "http://uri.suomi.fi/codelist/ptv/ptvkohderyhmat/code/KR1.6"
NAME_RE = re.compile(r"vamm(?!al)|kehitysvam|autis|näkövam|kuulovam|henkilökohtai\w* apu|erityis|asperger|adhd|viittoma|tulkkaus", re.I)
GENERIC_RE = re.compile(r"\bkela\b|suomi-piste|asiointipiste|yhteispalvelu|lähitori|kirjasto|terveysasema|virastotalo|kaupungintalo|kunnantalo|\binfo\b", re.I)
HOME_RE = re.compile(r"asumin|asumisen|ryhmäkot|ryhmäkod|asumisyksik|asumispalvel|palveluasu|tukiasu|asuntola|asumisyhteis|autettu asum|ohjattu asum|ryhmäasu|palvelukot|palvelukod|hoivakot|hoivakod|asumisväli|boendeenhet|gruppbostad|serviceboende", re.I)


_TM35 = Transformer.from_crs(3067, 4326, always_xy=True)


def to_wgs84(lat, lng):
    """PTV's `latitude`/`longitude` are WGS84 degrees on some records and ETRS-TM35FIN metres (northing/easting) on others."""
    try:
        a, b = float(lat), float(lng)
    except (TypeError, ValueError):
        return None, None
    if abs(a) > 90 or abs(b) > 180:
        x, y = _TM35.transform(b, a)
        return y, x
    return a, b


def cached_json(name, url):
    path = os.path.join(SCRATCH, name)
    if not os.path.exists(path):
        os.makedirs(SCRATCH, exist_ok=True)
        json.dump(rc.get_json(url, timeout=180, delay=0.3), open(path, "w"), ensure_ascii=False)
    return json.load(open(path))


def paged_ids(tag, url):
    ids, page = [], 1
    while True:
        d = cached_json(f"{tag}_p{page}.json", f"{url}&page={page}")
        ids += [x["id"] for x in d["itemList"]]
        if page >= d["pageCount"]:
            return ids
        page += 1


def batched(kind, ids, tag):
    out = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        d = cached_json(f"{tag}_{i // 50:04d}.json", f"{B}/{kind}/list?guids={','.join(chunk)}")
        for x in d:
            out[x["id"]] = x
    return out


def text(lst, langs=("fi", "sv", "en")):
    by = {x["language"]: x.get("value") for x in lst or [] if x.get("value")}
    for l in langs:
        if by.get(l):
            return rc.clean(by[l])
    return rc.clean(next(iter(by.values()), ""))


def main():
    os.makedirs(SCRATCH, exist_ok=True)
    cand = []
    for u in CLASS_URIS:
        cand += paged_ids(u.rsplit("/", 1)[1], f"{B}/Service/serviceClass?uri={u}")
    cand += paged_ids("KR16", f"{B}/Service/targetGroup?uri={TARGET_URI}")
    cand = list(dict.fromkeys(cand))
    print(f"{len(cand)} candidate services")
    services = batched("Service", cand, "svc")
    core_svc, broad_svc = {}, {}
    for sid, s in services.items():
        classes = {c.get("code") for c in s.get("serviceClasses") or []}
        targets = {t.get("code") for t in s.get("targetGroups") or []}
        name = text(s.get("serviceNames"))
        if classes & CORE_CLASSES or NAME_RE.search(name):
            core_svc[sid] = s
        elif "KR1.6" in targets:
            broad_svc[sid] = s
    print(f"{len(core_svc)} core services, {len(broad_svc)} broad services")
    chan_service = {}
    for tier, group in (("broad", broad_svc), ("core", core_svc)):   # core wins
        for sid, s in group.items():
            for c in s.get("serviceChannels") or []:
                chan_service[c["serviceChannel"]["id"]] = (tier, text(s.get("serviceNames")))
    chans = batched("ServiceChannel", list(chan_service), "chan")
    locs = {cid: c for cid, c in chans.items() if c.get("serviceChannelType") == "ServiceLocation" and c.get("publishingStatus") == "Published"}
    print(f"{len(chans)} channels, {len(locs)} published service locations")
    orgs = batched("Organization", list({c["organizationId"] for c in locs.values() if c.get("organizationId")}), "org")

    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="fi")
    out = {"core": [], "broad": []}
    homes = {}   # (tier, org id, municipality) -> info
    generic = nocoord = 0
    for cid, c in locs.items():
        tier, svc_name = chan_service[cid]
        name = text(c.get("serviceChannelNames"))
        if GENERIC_RE.search(name):
            generic += 1
            continue
        addr = next((a for a in c.get("addresses") or [] if (a.get("streetAddress") or {}).get("latitude")), None)
        if not addr:
            nocoord += 1
            continue
        sa = addr["streetAddress"]
        lat, lng = to_wgs84(sa["latitude"], sa["longitude"])
        if not rc.plausible("FI", lat, lng):
            nocoord += 1
            continue
        muni = text((sa.get("municipality") or {}).get("name")) if isinstance(sa.get("municipality"), dict) else ""
        street = text(sa.get("street"))
        number = rc.clean(sa.get("streetNumber"))
        postal = rc.clean(sa.get("postalCode"))
        post_office = text(sa.get("postOffice")) if isinstance(sa.get("postOffice"), list) else rc.clean(sa.get("postOffice"))
        muni = muni or post_office.title()
        org = orgs.get(c.get("organizationId")) or {}
        org_name = text(org.get("organizationNames")) if org else ""
        if HOME_RE.search(name) or HOME_RE.search(svc_name):
            key = (tier, c.get("organizationId"), muni)
            homes.setdefault(key, {"org": org_name or name, "muni": muni, "n": 0, "svc": svc_name, "web": None})
            homes[key]["n"] += 1
            continue
        phone = next((rc.clean(p.get("number")) and ("+" + rc.clean(p.get("prefixNumber") or "").lstrip("+") + " " + rc.clean(p["number"]) if p.get("prefixNumber") else rc.clean(p["number"]))
                      for p in c.get("phoneNumbers") or [] if p.get("number")), None) if c.get("phoneNumbers") else None
        web = next((w["url"] for w in c.get("webPages") or [] if w.get("url")), None)
        full = ", ".join(x for x in (f"{street} {number}".strip(), f"{postal} {post_office}".strip() if post_office else postal) if x)
        label = f"{name} ({org_name})" if org_name and org_name.lower() not in name.lower() and len(name) < 40 else name
        desc = f"{svc_name}." + (f" Operator: {org_name}." if org_name else "")
        out[tier].append(rc.entry(label, SOURCE, "social", ["Information & Support"], desc, address=full or muni, phone=phone,
                                  website=rc.clean_url(web), lat=lat, lng=lng, external_id=f"ptv:{cid}", breadth=tier, scope="general"))
    # housing units: one entry per operator and municipality, at the municipality centre
    nohome = 0
    for (tier, oid, muni), h in homes.items():
        addr, eid = f"{muni}, Finland", f"ptv-housing:{oid}:{muni}"
        # coordinates already in the dataset for this entry, else Nominatim
        hit = rc.prior_coords(eid, addr) or geoc.geocode(addr)
        if not hit or not rc.plausible("FI", *hit):
            nohome += 1
            continue
        n = f"{h['n']} housing units" if h["n"] > 1 else "housing unit"
        out[tier].append(rc.entry(f"{h['org']} - supported housing, {muni}", SOURCE, "social", ["Residential & Social Care"],
                                  f"{h['svc']}. {n.capitalize()} for people with disabilities in {muni} (location shown at municipality level; housing addresses are not published here).",
                                  address=addr, lat=hit[0], lng=hit[1], external_id=eid,
                                  breadth=tier, scope="general"))
    print(f"dropped: {generic} generic service points, {nocoord} without coordinates, {nohome} housing groups without a geocode; "
          f"{sum(h['n'] for h in homes.values())} housing locations collapsed into {len(homes)} municipality entries")
    core = rc.finalize(os.path.join(rc.REPO, "new_resources_ptv.json"), out["core"])
    rc.finalize(os.path.join(rc.REPO, "new_resources_ptv_broad.json"), out["broad"])
    rc.spot_check(core, 10, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
