#!/usr/bin/env python3
"""
Bosnia and Herzegovina, two small HTML sources (shard BA, joined to the e-register of associations in bosnia_fetch.py):
  BA2  FBiH Federal Ministry of Labour and Social Policy, "Adresar JU socijalne zastite"
       https://fmrsp.gov.ba/ju-socijalne-zastite  (101 institutions, one table). Core = disability institutions only:
       placement type "invaliditetom" / "Stanovanje u zajednici" / "Skrb izvan vlastite obitelji", or a name with
       "posebnim potrebama" / "teskocama u razvoju" / "odgoj i obrazovanje" (Zavod Sarajevo, Sveta obitelj Mostar).
       NEVER built: women's safe houses ("sigurne kuce / skloništa", excluded by type before anything else), elderly homes,
       children without parental care, addiction communities, street-children centres, reform schools.
       Community-living and out-of-family-care residences (SUMERO, Kuca nade, Put u zivot, Emmaus Duje) are shown at town level.
  BA4  Sarajevo Canton Ministry of Education, https://mo.ks.gov.ba/ustanove/lista (275 institutions). Core = the special
       schools and their preschool units (Mjedenica, Vladimir Nazor, the blind/low-vision centre, the hearing/speech centre).
  BA3  FBiH social-work centres, https://fmrsp.gov.ba/adresar-centara-i-lokalnih-sluzbi-za-socijalni-rad-u-federaciji-bih
       (80 rows, one table). BROAD: they are the access points for disability benefits and status assessment, not
       disability-specific. The contact-person and e-mail columns are never read. Id ba-csr:<canton>-<town>-<body>.
Privacy: only the institution's landline is kept (mobile numbers and e-mails dropped); no contact person is on either page.
Output: new_resources_bosnia_inst.json   Raw: tools/bosnia_inst_scratch/*.html   Nominatim, 1 req/s.
"""
import html
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "bosnia_inst_scratch")
URL_FBIH = "https://fmrsp.gov.ba/ju-socijalne-zastite"
URL_KS = "https://mo.ks.gov.ba/ustanove/lista"
SRC_FBIH = "Bosnia and Herzegovina FBiH Ministry of Labour and Social Policy social-protection institutions (fmrsp.gov.ba)"
URL_CSR = "https://fmrsp.gov.ba/adresar-centara-i-lokalnih-sluzbi-za-socijalni-rad-u-federaciji-bih"
SRC_CSR = "Bosnia and Herzegovina FBiH social-work centres directory (fmrsp.gov.ba)"
SRC_KS = "Bosnia and Herzegovina Sarajevo Canton Ministry of Education institutions list (mo.ks.gov.ba)"
SAFE_HOUSE = re.compile(r"sigurne ku", re.I)
CORE_TYPE = re.compile(r"invalid|stanovanje u zajednici|skrb izvan vlastite", re.I)
CORE_NAME = re.compile(r"posebnim potrebama|te[sš]ko[cć]ama u razvoju|odgoj i obrazovanje|invalid", re.I)
TOWN_ONLY = re.compile(r"stanovanje u zajednici|skrb izvan vlastite|prihvatni centar", re.I)
KS_SPECIAL = re.compile(r"mjedenic|vladimir nazor|slijepu i slabovidnu|slu[sš]nu i govornu", re.I)


def page(url, name):
    p = os.path.join(SCRATCH, name)
    if not os.path.exists(p):
        os.makedirs(SCRATCH, exist_ok=True)
        open(p, "wb").write(rc.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; AccessibilityMapper registry builder)"}))
    return open(p, encoding="utf-8", errors="replace").read()


def table(h):
    rows = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        c = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip() for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        links = re.findall(r'href="(https?://[^"]+)"', r)
        rows.append((c, links))
    return rows


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().translate(str.maketrans("šćčžđ", "sccz" "d"))).strip("-")[:70]


def landline(s):
    """First landline in a phone cell; mobile numbers (06x) are dropped."""
    for part in re.split(r"[;,]", s):
        d = re.sub(r"\D", "", part)
        if len(d) >= 8 and not d.startswith(("06", "3876", "00386")) and part.strip() not in ("-", ""):
            return re.sub(r"\s*/\s*\d{1,3}$", "", re.sub(r"\s+", " ", part.strip()))  # drop a trailing "/ 053" extension
    return None


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def locate(geoc, street, town, town_only):
    """(lat, lng, precise). A street hit is kept only within 15 km of the town centre (Nominatim matches same-named streets elsewhere)."""
    centre = geoc.geocode(f"{town}, Bosna i Hercegovina")
    if centre and not rc.plausible("BA", *centre):
        centre = None
    if town_only or not street:
        return (centre + (False,)) if centre else None
    st = re.sub(r"\b(b\.?\s?b\.?|bb)\b\.?", "", street, flags=re.I).strip(" ,.")
    hit = geoc.geocode(f"{st}, {town}, Bosna i Hercegovina") if st else None
    if hit and rc.plausible("BA", *hit) and (not centre or km(hit, centre) <= 15):
        return hit + (True,)
    return (centre + (False,)) if centre else None


def main():
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="ba")
    rc.STATUS["input"] = "fmrsp.gov.ba ju-socijalne-zastite + mo.ks.gov.ba ustanove/lista"
    out, skipped = [], []
    for c, _ in table(page(URL_FBIH, "ju.html"))[1:]:
        if len(c) < 6 or not re.match(r"\d+\.?$", c[0]):
            continue
        name, typ, owner, town, street = c[1], c[2], c[3], c[4], (c[5] if c[5] != "-" else "")
        phone = landline(c[6]) if len(c) > 6 else None
        if SAFE_HOUSE.search(typ):  # women's safe houses: never published
            continue
        if not (CORE_TYPE.search(typ) or CORE_NAME.search(name)):
            continue
        town_only = bool(TOWN_ONLY.search(typ) or TOWN_ONLY.search(name))
        loc = locate(geoc, street, town, town_only)
        if not loc:
            skipped.append(name)
            continue
        lat, lng, precise = loc
        day = bool(re.search(r"dnev|poludnev", typ + " " + name, re.I))
        svc = ["Day programs", "Residential & Social Care"] if day else ["Residential & Social Care", "Supported living"]
        addr = (f"{street}, " if precise else "") + f"{town}, Bosna i Hercegovina"
        out.append(rc.entry(rc.clean(name), SRC_FBIH, "social", svc,
                            f"FBiH social-protection institution ({rc.clean(typ)}; founder: {rc.clean(owner)}), listed in the Federal Ministry's directory.",
                            address=addr, phone=phone, lat=lat, lng=lng, external_id=f"ba-fbih:{slug(name)}-{slug(town)}", scope="general"))
    nf = len(out)
    for c, links in table(page(URL_KS, "ks.html"))[1:]:
        if len(c) < 5 or not KS_SPECIAL.search(c[0]):
            continue
        name, tip, muni, street = c[0], c[1], c[2], c[3]
        loc = locate(geoc, street, f"{muni}, Sarajevo", False)
        if not loc:
            skipped.append(name)
            continue
        lat, lng, precise = loc
        web = rc.clean_url(links[0]) if links else None
        pre = "preschool" in tip.lower() or "predškolske" in tip.lower() or "predskolske" in tip.lower()
        out.append(rc.entry(rc.clean(name), SRC_KS, "education", ["Special education", "Education"],
                            "Special education institution in Sarajevo Canton" + (" (preschool unit)" if pre else "") + ", from the Cantonal Ministry of Education list.",
                            address=f"{street}, {muni}, Sarajevo, Bosna i Hercegovina", website=web, lat=lat, lng=lng,
                            external_id=f"ba-ks:{slug(name)}-{slug(tip)}", scope="general"))
    nk = len(out)
    for c, _ in table(page(URL_CSR, "csr.html"))[1:]:
        if len(c) < 7 or not re.match(r"\d+\.?$", c[0]):
            continue
        body, canton, town, street = c[1], c[2], c[3], (c[5] if c[5] != "-" else "")   # c[4] contact person, c[7] e-mail: not read
        loc = locate(geoc, street, town, False)
        if not loc:
            skipped.append(f"{body} {town}")
            continue
        lat, lng, precise = loc
        ph = landline(re.sub(r"(\d)\s+(?=\d{2,3}/)", r"\1;", c[6]))
        out.append(rc.entry(f"{rc.clean(body)} {rc.clean(town)}", SRC_CSR, "social", ["Information & Support"],
                            f"Social-work centre / local social-welfare service ({rc.clean(canton)}); access point for disability benefits and status assessment. Listed in the FBiH Federal Ministry directory.",
                            address=(f"{street}, " if precise else "") + f"{town}, Bosna i Hercegovina", phone=ph, lat=lat, lng=lng,
                            external_id=f"ba-csr:{slug(canton)}-{slug(town)}-{slug(body)}", breadth="broad", scope="general"))
    print(f"FBiH institutions {nf}; Sarajevo Canton special schools {nk - nf}; FBiH social-work centres {len(out) - nk}; skipped (no geocode) {skipped}")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_bosnia_inst.json"), out)
    for e in fin:
        print(f"  {e['external_id'][:60]:<60} {e['name'][:50]:<50} | {e.get('address')} | {e.get('phone')} | {e['coordinates']}")


if __name__ == "__main__":
    main()
