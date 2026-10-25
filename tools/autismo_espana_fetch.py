#!/usr/bin/env python3
"""
Autismo España (Confederación Autismo España) member and linked entities, https://autismo.org.es/nosotros/entidades-miembro/
One static HTML page (no CAPTCHA on the list; the reCAPTCHA is on a contact form), ~508 blocks: "Entidad Socia" (~253 member
associations) and "Entidad Vinculada" (~255 linked entities). Autism-specific, so no disability_scope.
Each block: name, address lines (street / CP postcode / town (province)), phone, e-mail, website. The e-mail is never read;
phones are kept only when they are landlines (Spanish 8xx/9xx), not mobiles (6xx/7xx). Generic social-media pages are not
used as a website. Located with Nominatim (street + postcode + town, falling back to postcode + town, then town; cache
geocode_cache.jsonl); an address hit is kept only within 30 km of the town centre.
Id autismo-es:<slug of name>-<slug of town>; blocks without an address and repeats of an entity are skipped (194 distinct names in 508 blocks). Overlap with the regional Spanish registers is removed by the merge step
(name + region) and tools/dedupe_registry_vs_manual.py (website).
Output: new_resources_autismo_espana.json   Raw: tools/autismo_espana_scratch/entidades.html
"""
import collections
import html
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "autismo_espana_scratch")
URL = "https://autismo.org.es/nosotros/entidades-miembro/"
SRC = "Autismo España member and linked entities directory (autismo.org.es)"
SOCIAL = re.compile(r"facebook\.|instagram\.|twitter\.|x\.com|linkedin\.|youtube\.|blogspot\.|wordpress\.com|wixsite", re.I)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))).strip("-")[:50]


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def text(s):
    return rc.clean(html.unescape(re.sub(r"<[^>]+>", " ", s or "")))


def field(b, cls):
    m = re.search(rf'list__aso_{cls}">(.*?)</div>', b, re.S)
    return m.group(1) if m else ""


def landline(s):
    for part in re.split(r"<br\s*/?>|[/,;]", s):
        d = re.sub(r"\D", "", part)
        d = d[2:] if d.startswith("34") and len(d) == 11 else d
        if len(d) == 9 and d[0] in "89":
            return f"{d[:3]} {d[3:6]} {d[6:]}"
    return None


def page():
    p = os.path.join(SCRATCH, "entidades.html")
    if not os.path.exists(p):
        os.makedirs(SCRATCH, exist_ok=True)
        open(p, "wb").write(rc.get(URL, timeout=60))
    return open(p, encoding="utf-8", errors="replace").read()


def main():
    h = page()
    blocks = re.split(r'<div class="list__aso ', h)[1:]
    if len(blocks) < 400:
        raise RuntimeError(f"Autismo España: {len(blocks)} blocks, expected ~508 -- page layout changed?")
    rc.STATUS["input"] = f"autismo.org.es entidades-miembro, {len(blocks)} blocks"
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="es")
    out, skip, seen = [], collections.Counter(), set()
    for b in blocks:
        bid = re.search(r'id="asociacion_(\d+)"', b)
        name = text(field(b, "nombre"))
        lines = [text(x) for x in re.split(r"<br\s*/?>", field(b, "direccion")) if text(x)]
        if not name or not bid or not lines:
            skip["no name/address"] += 1
            continue
        if (slug(name), slug(lines[-1])) in seen:   # the page repeats an entity once per province it covers
            skip["repeated block"] += 1
            continue
        seen.add((slug(name), slug(lines[-1])))
        cp = next((re.search(r"\d{5}", x).group() for x in lines if re.match(r"CP\s*\d{5}", x)), None)
        rest = [x for x in lines if not re.match(r"CP\s*\d{5}", x)]
        town = rest[-1] if rest else ""            # "Town (Province)" is the last line; venue and street lines come before it
        street = ", ".join(rest[:-1])
        tm = re.match(r"(.*?)\s*\((.*?)\)\s*$", town)
        city, prov = (tm.group(1), tm.group(2)) if tm else (town, "")
        if not city:
            skip["no town"] += 1
            continue
        centre = geoc.geocode(f"{cp or ''} {city}, {prov}, España".replace("  ", " ").strip())
        hit = None
        if street:
            hit = geoc.geocode(f"{street}, {cp or ''} {city}, {prov}, España".replace("  ", " "))
            if hit and (not rc.plausible("ES", *hit) or (centre and km(hit, centre) > 30)):
                hit = None
        loc = hit or centre
        if not loc or not rc.plausible("ES", *loc):
            skip["no location"] += 1
            continue
        web = None
        w = re.search(r'href="(https?://[^"]+)"', field(b, "web"))
        if w and not SOCIAL.search(w.group(1)):
            web = rc.clean_url(w.group(1))
        tipo = text(field(b, "tipo"))
        addr = ", ".join(x for x in (street if hit else "", f"{cp} {city}" if cp else city, prov, "España") if x)
        out.append(rc.entry(name, SRC, "advocacy", ["Advocacy", "Information & Support", "Peer Support"],
                            f"Autism association ({tipo.lower()} of Confederación Autismo España){' in ' + prov if prov else ''}.",
                            address=addr, phone=landline(field(b, "tel")), website=web, lat=loc[0], lng=loc[1],
                            external_id=f"autismo-es:{slug(name)}-{slug(city)}"))
    print(f"{len(blocks)} blocks; {len(out)} built; skipped {dict(skip)}")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_autismo_espana.json"), out)
    rc.spot_check(fin, 12, fields=("name", "address", "website"))


if __name__ == "__main__":
    main()
