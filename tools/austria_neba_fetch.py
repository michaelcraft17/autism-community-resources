#!/usr/bin/env python3
"""
Austria NEBA (Netzwerk Berufliche Assistenz) provider lists + Behindertenrat member list (HTML scrapes; shard AT).
  NEBA   https://www.neba.at/anbieterinnen/liste/<service>?start=N  (20 per page; name, address, website only)
         core:  arbeitsassistenz, jobcoaching, berufsausbildungsassistenz
         broad: jugendcoaching, ausbildungsfit (transition support for all young people at risk, not only disability)
         betriebsservice is an employer service, not built.
  Behindertenrat  https://www.behindertenrat.at/ueber-uns/mitglieder/  (umbrella members, HQ address only)
Privacy: NEBA phone numbers exist only in the per-person "Kontaktperson" block of detail pages, which are never fetched,
so no phone is kept. Behindertenrat e-mails and mobile numbers (06xx) are dropped; landline organisation numbers kept.
Output: new_resources_austria_neba.json   Scratch: tools/neba_scratch/   Nominatim, 1 req/s.
"""
import html
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "neba_scratch")
SERVICES = {  # slug: (breadth, label, description)
    "arbeitsassistenz": ("core", "Arbeitsassistenz", "NEBA workplace assistance: helps people with disabilities find and keep a job"),
    "jobcoaching": ("core", "Jobcoaching", "NEBA job coaching: on-the-job support for people with disabilities"),
    "berufsausbildungsassistenz": ("core", "Berufsausbildungsassistenz", "NEBA vocational training assistance for young people with disabilities in apprenticeships"),
    "jugendcoaching": ("broad", "Jugendcoaching", "NEBA youth coaching for young people at risk of dropping out, including those with disabilities or special educational needs"),
    "ausbildungsfit": ("broad", "AusbildungsFit", "NEBA AusbildungsFit: preparation for training for young people who are not yet ready, including those with disabilities"),
}
SRC_NEBA = "Austria NEBA Netzwerk Berufliche Assistenz provider lists"
SRC_BR = "Austria Behindertenrat member organisations"
UA = {"User-Agent": "Mozilla/5.0 (compatible; AccessibilityMapper registry builder)"}


def page(url, name):
    p = os.path.join(SCRATCH, name)
    if not os.path.exists(p):
        os.makedirs(SCRATCH, exist_ok=True)
        raw = rc.get(url, headers=UA)
        open(p, "wb").write(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
        time.sleep(1)
    return open(p, encoding="utf-8", errors="replace").read()


def txt(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def split_address(a):
    """(PLZ, Ort, street) from the free-text NEBA address; first PLZ wins, so multi-site rows use their first site."""
    a = re.sub(r"\bA-(?=\d{4})", "", a)
    m = re.search(r"\b(\d{4})\b", a)
    if not m:
        return None, None, a
    plz = m.group(1)
    om = re.search(plz + r"\s+([A-ZÄÖÜ][^,/(\d]*?)(?=\s*(?:,|/|\(|$| und ))", a)
    parts = [p.strip() for p in re.sub(r"\b\d{4}\b", ",", a).split(",") if p.strip()]
    ort = om.group(1).strip() if om else next((p for p in parts if not re.search(r"\d", p) and p != "Oberösterreich"), None)
    street = next((p for p in parts if re.search(r"\d", p)), "")
    return (plz, ort, street) if ort else (plz, None, street)


NOT_ORGS = {"Fördernde Mitglieder", "Ehrenmitglieder und Ehrenpräsidenten"}


def neba(geoc):
    out, skipped = [], 0
    for slug, (breadth, label, desc) in SERVICES.items():
        start, n, seen = 0, 0, set()
        while True:
            h = page(f"https://www.neba.at/anbieterinnen/liste/{slug}" + (f"?start={start}" if start else ""), f"{slug}_{start}.html")
            items = re.findall(r'<li class="el-item">\s*<div class="el-content uk-panel"><h3>(.*?)</li>', h, re.S)
            ids = set(re.findall(r"-?(cdo\d+)", "".join(items)))
            if not items or not (ids - seen):  # the site repeats the last page for an out-of-range start
                break
            seen |= ids
            for it in items:
                m = re.search(r'box-name-organisation">(.*?)</span>', it, re.S)
                h4 = re.search(r"<h4>(.*?)</h4>", it, re.S)
                adr = re.search(r"<strong>Adresse:</strong>(.*?)<br", it, re.S)
                web = re.search(r'<strong>Website:</strong>\s*<a href="([^"]+)"', it)
                cid = re.search(r"-?(cdo\d+)", it)
                if not (m and adr and cid):
                    skipped += 1
                    continue
                org, prog, a = txt(m.group(1)), txt(h4.group(1)) if h4 else label, txt(adr.group(1))
                plz, ort, street = split_address(a)
                if plz and ort:
                    hit = (street and geoc.geocode(f"{street}, {plz} {ort}, Österreich")) or geoc.geocode(f"{plz} {ort}, Österreich")
                else:  # no usable town: let the geocoder read the street with its PLZ, or the whole text
                    hit = geoc.geocode(f"{street}, {plz}, Österreich" if plz else f"{street}, Österreich")
                if not hit or not rc.plausible("AT", *hit):
                    skipped += 1
                    continue
                out.append(rc.entry(f"{org} - {prog}", SRC_NEBA, "social", ["Employment Support"], desc + ".",
                                    address=f"{a}, Austria", website=rc.clean_url(web.group(1)) if web else None,
                                    lat=hit[0], lng=hit[1], external_id=f"at-neba:{cid.group(1)}", breadth=breadth, scope="general"))
                n += 1
            if len(items) < 20:
                break
            start += 20
        print(f"NEBA {slug}: {n}")
    return out, skipped


def behindertenrat(geoc):
    h = page("https://www.behindertenrat.at/ueber-uns/mitglieder/", "mitglieder.html")
    h = h[h.find('class="entry-content'):]
    out, skipped = [], 0
    for name, body in re.findall(r'<h3 class="wp-block-heading">(.*?)</h3>\s*<p class="wp-block-paragraph">(.*?)</p>', h, re.S):
        name = re.sub(r"\s*\((?:P|M|[A-Z])\)\s*$", "", txt(name))
        if name in NOT_ORGS or name.endswith("?"):  # page headings, not member organisations
            continue
        web = re.search(r'href="(https?://[^"]+)"[^>]*>(?!\s*[^<]*@)', body)
        lines = [txt(x) for x in re.split(r"<br\s*/?>", re.sub(r"<a [^>]*>.*?</a>", "", body, flags=re.S))]
        plz_i = next((i for i, l in enumerate(lines) if re.match(r"\d{4}\s+\S", l)), None)
        tel = next((re.sub(r"^Tel:?\s*", "", l) for l in lines if l.lower().startswith("tel")), "")
        if tel and re.match(r"\+?(43)?\s*0?6\d\d", tel.replace("-", "").replace(" ", "")) and re.match(r"\s*(\+43|0)\s*6[4-9]", tel):
            tel = ""  # mobile number
        if plz_i is None:
            out.append(rc.entry(name, SRC_BR, "advocacy", ["Advocacy", "Information & Support"],
                                "Member organisation of the Austrian Disability Council (Behindertenrat).", phone=tel or None,
                                website=rc.clean_url(web.group(1)) if web else None, placeless=True,
                                external_id=f"at-br:{re.sub(r'[^a-z0-9]+', '-', name.lower())[:60]}", breadth="core", scope="general"))
            continue
        plz, ort = re.match(r"(\d{4})\s+(.+)", lines[plz_i]).groups()
        street = lines[plz_i - 1] if plz_i > 0 and not lines[plz_i - 1].lower().startswith(("gemeinn", "verein")) else ""
        hit = (street and geoc.geocode(f"{street}, {plz} {ort}, Österreich")) or geoc.geocode(f"{plz} {ort}, Österreich")
        if not hit or not rc.plausible("AT", *hit):
            skipped += 1
            continue
        out.append(rc.entry(name, SRC_BR, "advocacy", ["Advocacy", "Information & Support"],
                            "Member organisation of the Austrian Disability Council (Behindertenrat).",
                            address=f"{street + ', ' if street else ''}{plz} {ort}, Austria", phone=tel or None,
                            website=rc.clean_url(web.group(1)) if web else None, lat=hit[0], lng=hit[1],
                            external_id=f"at-br:{re.sub(r'[^a-z0-9]+', '-', name.lower())[:60]}", breadth="core", scope="general"))
    print(f"Behindertenrat: {len(out)}")
    return out, skipped


def main():
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="at")
    a, s1 = neba(geoc)
    b, s2 = behindertenrat(geoc)
    print(f"skipped (no geocode / malformed): NEBA {s1}, Behindertenrat {s2}")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_austria_neba.json"), a + b)
    rc.spot_check(out, 12)


if __name__ == "__main__":
    main()
