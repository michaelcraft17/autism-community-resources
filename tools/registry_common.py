#!/usr/bin/env python3
"""
Shared plumbing for the registry fetchers added from 2026-10-12 on (GIAS, FINESS, STIL, Skolverket, ...),
so each fetcher only holds what is specific to its source:

  get / get_json      HTTP with a research User-Agent, retries and a polite per-host delay
  Geocoder            Nominatim at <= 1 request/second, answers (including misses) cached on disk
  plausible()         country bounding boxes -- implausible coordinates are dropped, never published
  entry()             builds a resource-schema row (same keys/order as russia_build.py)
  finalize()          dedupes on external_id, refuses duplicate (name, address, source) triples (the
                      app derives a listing's id from them and shows one listing per id), writes the file
  spot_check()        prints N random rows for the by-eye check the build rules ask for

Schema: name, address, phone, website, type (advocacy/therapy/education/medical/social/general_support),
source, services, description, coordinates {lat,lng}, external_id ("<prefix>:<registry id>"), breadth
("core"/"broad"), disability_scope ("general"/"neurodevelopmental"; absent for autism-specific sources).
placeless is set only when a row genuinely has no location.
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
VALID_TYPES = {"advocacy", "therapy", "education", "medical", "social", "general_support"}

# (south, north, west, east) boxes; a list means "any of these".
BBOX = {
    "US": [(17.5, 72.0, -180.0, -64.0), (-15.0, -10.0, -172.0, -168.0), (4.0, 21.0, 130.0, 180.0)],
    "GB": [(49.8, 61.0, -8.8, 1.9)],
    "FR": [(41.2, 51.2, -5.5, 9.8), (15.7, 16.7, -61.9, -60.9), (14.3, 15.0, -61.3, -60.7), (1.9, 6.0, -55.0, -51.0),
           (-21.5, -20.8, 55.0, 56.0), (-13.2, -12.5, 44.9, 45.4), (46.7, 47.2, -56.6, -56.0), (17.8, 18.2, -63.2, -62.7),
           (-28.0, -7.0, -155.0, -134.0), (-23.0, -19.0, 163.0, 169.0), (-14.5, -13.0, -178.5, -176.0)],
    "DK": [(54.5, 57.8, 8.0, 15.3), (61.3, 62.4, -7.8, -6.2), (59.0, 84.0, -75.0, -10.0)],
    "SE": [(55.2, 69.2, 10.9, 24.3)],
    "NO": [(57.9, 71.3, 4.3, 31.3), (74.0, 81.0, 9.0, 35.0)],
    "FI": [(59.7, 70.2, 19.0, 31.7)],
    "EE": [(57.4, 59.8, 21.6, 28.3)],
    "LV": [(55.6, 58.1, 20.9, 28.3)],
    "PL": [(48.9, 54.9, 14.0, 24.2)],
    "JP": [(24.0, 46.0, 122.5, 146.5), (20.0, 21.0, 136.0, 137.0), (24.0, 25.0, 153.5, 154.5)],
    "AU": [(-44.0, -9.0, 112.0, 154.5), (-12.5, -12.0, 96.5, 97.2), (-10.7, -10.3, 105.4, 105.8)],
    "NZ": [(-48.0, -34.0, 166.0, 179.0), (-44.5, -43.5, -177.0, -175.5)],
    "CA": [(41.5, 84.0, -141.1, -52.0)],
    "MX": [(14.4, 32.8, -118.5, -86.5)],
    "CO": [(-4.3, 13.5, -79.1, -66.8)],
    "AR": [(-55.2, -21.7, -73.7, -53.5)],
    "IL": [(29.4, 33.4, 34.2, 35.95)],
    "ES": [(35.8, 43.9, -9.5, 4.5), (27.5, 29.5, -18.4, -13.3)],
    "MD": [(45.4, 48.5, 26.6, 30.2)],
    "ME": [(41.8, 43.6, 18.4, 20.4)],
}


def plausible(cc, lat, lng):
    if lat is None or lng is None:
        return False
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    if lat == 0 and lng == 0:
        return False
    boxes = BBOX.get(cc)
    if not boxes:
        return -90 <= lat <= 90 and -180 <= lng <= 180
    return any(s <= lat <= n and w <= lng <= e for s, n, w, e in boxes)


_last_request = {}


def get(url, *, data=None, headers=None, timeout=90, retries=3, delay=0.0, method=None, browser=False):
    """Bytes of the response; retries with backoff. `delay` = minimum seconds between requests to a host."""
    hdr = {"User-Agent": BROWSER_UA if browser else UA}
    hdr.update(headers or {})
    host = urllib.parse.urlsplit(url).netloc
    err = None
    for attempt in range(retries):
        if delay:
            wait = delay - (time.time() - _last_request.get(host, 0))
            if wait > 0:
                time.sleep(wait)
        _last_request[host] = time.time()
        try:
            req = urllib.request.Request(url, data=data, headers=hdr, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            err = e
            if e.code in (400, 401, 403, 404):
                raise
            time.sleep(3 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(3 * (attempt + 1))
    raise err


def get_json(url, **kw):
    return json.loads(get(url, **kw))


def download(url, path, **kw):
    """Download to `path` once (cached); returns the path."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(get(url, timeout=kw.pop("timeout", 600), **kw))
        os.replace(tmp, path)
    return path


class Geocoder:
    """Nominatim, 1 request/second, results (including misses) cached in a jsonl file next to the fetcher."""

    def __init__(self, cache_path, countrycodes=None):
        self.cache_path = cache_path
        self.countrycodes = countrycodes
        self.cache = {}
        self.fresh = 0
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        if os.path.exists(cache_path):
            for line in open(cache_path, encoding="utf-8"):
                try:
                    d = json.loads(line)
                    self.cache[d["q"]] = d["c"]
                except Exception:  # noqa: BLE001
                    pass

    def geocode(self, q, countrycodes=None):
        if not q:
            return None
        key = q if not (countrycodes or self.countrycodes) else q
        if key in self.cache:
            c = self.cache[key]
            return tuple(c) if c else None
        params = {"q": q, "format": "json", "limit": 1}
        cc = countrycodes or self.countrycodes
        if cc:
            params["countrycodes"] = cc
        res = None
        ok = False
        for attempt in range(3):
            try:
                data = json.loads(get(NOMINATIM + "?" + urllib.parse.urlencode(params), delay=1.05, timeout=30, retries=1))
                res = [float(data[0]["lat"]), float(data[0]["lon"])] if data else None
                ok = True
                break
            except Exception:  # noqa: BLE001
                time.sleep(5 * (attempt + 1))
        if not ok:
            return None   # transient failure: don't cache a miss
        self.cache[key] = res
        self.fresh += 1
        with open(self.cache_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"q": q, "c": res}, ensure_ascii=False) + "\n")
        return tuple(res) if res else None


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()


def clean_url(u):
    u = clean(u)
    if not u or u in ("-", "n/a", "N/A") or " " in u:
        return None
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    return u if re.search(r"\.[a-z]{2,}", u, re.I) else None


def entry(name, source, type_, services, description, *, address=None, phone=None, website=None, lat=None, lng=None,
          external_id=None, breadth="core", scope=None, placeless=False):
    """One resource-schema row; empty fields are omitted, as in the existing shards."""
    assert type_ in VALID_TYPES, type_
    e = {"name": clean(name)}
    if address:
        e["address"] = clean(address)
    if phone:
        e["phone"] = clean(phone)
    if website:
        e["website"] = website
    e.update({"type": type_, "source": source, "services": list(services), "description": clean(description)})
    if lat is not None and lng is not None:
        e["coordinates"] = {"lat": round(float(lat), 6), "lng": round(float(lng), 6)}
    elif placeless:
        e["placeless"] = True
    if external_id:
        e["external_id"] = external_id
    e["breadth"] = breadth
    if scope:
        e["disability_scope"] = scope
    return e


def finalize(path, entries, *, require_location=True):
    """Dedupe on external_id, refuse id collisions, write `path`. Returns the entries written."""
    seen_ids, seen_triples, out, dup_id, dup_triple, nolocation = set(), set(), [], 0, 0, 0
    for e in entries:
        if require_location and not e.get("coordinates") and not e.get("placeless"):
            nolocation += 1
            continue
        eid = e.get("external_id")
        if eid in seen_ids:
            dup_id += 1
            continue
        t = (e["name"], e.get("address", ""), e["source"])
        if t in seen_triples:
            dup_triple += 1
            continue
        if eid:
            seen_ids.add(eid)
        seen_triples.add(t)
        out.append(e)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"Wrote {os.path.basename(path)}: {len(out)} entries "
          f"(dropped: {dup_id} duplicate external_id, {dup_triple} duplicate name|address|source, {nolocation} without location)")
    return out


def spot_check(entries, n=30, seed=7, fields=("name", "address", "type", "external_id")):
    rnd = random.Random(seed)
    for e in rnd.sample(entries, min(n, len(entries))):
        c = e.get("coordinates") or {}
        print("  -", " | ".join(str(e.get(f, ""))[:70] for f in fields), f"| ({c.get('lat')}, {c.get('lng')})")


class Kartverket:
    """Norway's official address geocoder (ws.geonorge.no), keyless; answers cached in a jsonl file.

    address(street, postcode) -> (lat, lng) or None; municipality(kommunenummer) -> the municipality's
    representative point (used where only municipality-level location may be shown)."""

    def __init__(self, cache_path):
        self.cache_path = cache_path
        self.cache = {}
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        if os.path.exists(cache_path):
            for line in open(cache_path, encoding="utf-8"):
                try:
                    d = json.loads(line)
                    self.cache[d["q"]] = d["c"]
                except Exception:  # noqa: BLE001
                    pass

    def _remember(self, key, val):
        self.cache[key] = val
        with open(self.cache_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"q": key, "c": val}, ensure_ascii=False) + "\n")
        return tuple(val) if val else None

    def address(self, street, postcode, muni_nr=None):
        street = clean(street)
        if not street:
            return None
        key = f"a|{street}|{postcode}|{muni_nr or ''}"
        if key in self.cache:
            c = self.cache[key]
            return tuple(c) if c else None
        params = {"sok": street, "treffPerSide": 1, "utkoordsys": 4258}
        if postcode:
            params["postnummer"] = postcode
        if muni_nr:
            params["kommunenummer"] = muni_nr
        try:
            d = json.loads(get("https://ws.geonorge.no/adresser/v1/sok?" + urllib.parse.urlencode(params), delay=0.12, timeout=30, retries=2))
        except Exception:  # noqa: BLE001
            return None
        hits = d.get("adresser") or []
        p = hits[0].get("representasjonspunkt") if hits else None
        return self._remember(key, [p["lat"], p["lon"]] if p else None)

    def municipality(self, muni_nr):
        key = f"m|{muni_nr}"
        if key in self.cache:
            c = self.cache[key]
            return tuple(c) if c else None
        try:
            d = json.loads(get(f"https://ws.geonorge.no/kommuneinfo/v1/kommuner/{muni_nr}", delay=0.12, timeout=30, retries=2))
        except Exception:  # noqa: BLE001
            return None
        c = (d.get("punktIOmrade") or {}).get("coordinates")
        return self._remember(key, [c[1], c[0]] if c else None)


class MaaAmet:
    """Estonia's official address geocoder (Maa-amet in-ADS gazetteer), keyless; answers cached in a jsonl file.
    address(full_address) -> (lat, lng) or None. The service answers in L-EST97 (EPSG:3301)."""

    def __init__(self, cache_path):
        from pyproj import Transformer
        self.tr = Transformer.from_crs(3301, 4326, always_xy=True)
        self.cache_path = cache_path
        self.cache = {}
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        if os.path.exists(cache_path):
            for line in open(cache_path, encoding="utf-8"):
                try:
                    d = json.loads(line)
                    self.cache[d["q"]] = d["c"]
                except Exception:  # noqa: BLE001
                    pass

    def address(self, text):
        text = clean(text)
        if not text:
            return None
        if text in self.cache:
            c = self.cache[text]
            return tuple(c) if c else None
        try:
            d = json.loads(get("https://inaadress.maaamet.ee/inaadress/gazetteer?" + urllib.parse.urlencode({"address": text, "results": 1}),
                               delay=0.1, timeout=30, retries=2))
        except Exception:  # noqa: BLE001
            return None
        hits = d.get("addresses") or []
        val = None
        if hits and hits[0].get("viitepunkt_x"):
            lng, lat = self.tr.transform(float(hits[0]["viitepunkt_x"]), float(hits[0]["viitepunkt_y"]))   # x = easting, y = northing
            val = [round(lat, 6), round(lng, 6)]
        self.cache[text] = val
        with open(self.cache_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"q": text, "c": val}, ensure_ascii=False) + "\n")
        return tuple(val) if val else None
