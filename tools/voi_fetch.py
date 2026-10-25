#!/usr/bin/env python3
"""
Russia -- VOI (Vserossiyskoe Obshchestvo Invalidov, All-Russian Society of Disabled People) regional organisations,
the public list on https://www.voi.ru/o_nas/regionalnye_organizaci (one page per regional branch; ~86).

Each page gives address, phone, e-mail, website. The chairperson / audit-committee names on the page are personal
names and are never read. Entries are the organisation itself ("<Region> ... организация ВОИ"), type advocacy, core,
disability_scope general. The postal address is geocoded with Nominatim: the city first, then the street, kept only if it falls within ~5 km of the city centre
(Nominatim otherwise matches same-named streets in other towns); a PO-box address is pinned at the city. Branches in Crimea,
Sevastopol and the annexed Donetsk / Luhansk / Zaporizhzhia / Kherson regions are skipped. voi.ru answers a browser User-Agent only.
Output: new_resources_voi.json
"""
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "voi_scratch")
BASE = "https://www.voi.ru"
SOURCE = "Russia VOI (All-Russian Society of Disabled People) regional organisations directory"


DISPUTED = re.compile(r"Крым|Севастопол|Донецк|Луганск|Запорож|Херсон", re.I)


def lines_of(h):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [x.strip() for x in t.split("\n") if x.strip()], h


def after(lines, label):
    for j, x in enumerate(lines):
        if x == label and j + 1 < len(lines):
            return lines[j + 1]
    return None


def main():
    idx = rc.get(BASE + "/o_nas/regionalnye_organizaci", browser=True, delay=0.3).decode("utf-8", "replace")
    links = sorted(set(re.findall(r'href="(/o_nas/regionalnye_organizaci/[^"#?]+)"', idx)))
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="ru")
    out, nogeo, bad, disputed = [], 0, 0, 0
    for l in links:
        slug = l.rstrip("/").split("/")[-1]
        try:
            h = rc.get(BASE + l, browser=True, delay=0.3).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            rc.note_failure("voi.ru", f"{slug}: {e!r}")
            continue
        lines, _ = lines_of(h)
        # headline = the line after the last "Региональные организации" crumb before "Адрес"
        ai = lines.index("Адрес") if "Адрес" in lines else -1
        crumbs = [j for j, x in enumerate(lines[:ai]) if x == "Региональные организации"] if ai > 0 else []
        head = lines[crumbs[-1] + 1] if crumbs and crumbs[-1] + 1 < ai else None
        addr = after(lines, "Адрес")
        if not head or not addr or not re.search(r"\w", re.sub(r"\d{6}|[,\s]", "", addr)):
            bad += 1
            print(f"  {slug}: no usable name/address, skipped")
            continue
        head = rc.clean(re.sub(r",?\s*Организации\s*/.*$", "", head))
        name = head if re.search(r"ВОИ|Общество инвалидов", head, re.I) else f"{head} - Всероссийское общество инвалидов (ВОИ)"
        if DISPUTED.search(head + " " + addr):
            disputed += 1
            print(f"  {slug}: skipped (territory outside internationally recognised Russia; Nominatim cannot place it)")
            continue
        phone = after(lines, "Телефон")
        phone = phone if phone and re.match(r"[\d\-\(\)\s;+,.]{6,}", phone) else None
        site = after(lines, "Сайт")
        site = rc.clean_url(site) if site and not site.startswith("Социальные") else None
        a = rc.clean(addr).rstrip(", ")
        region = re.search(r"([А-ЯЁ][а-яё\-]+(?: [а-яё\-]+)? (?:область|край|округ)|Республика [А-ЯЁ][а-яё\- ]+?(?:,|$)|[А-ЯЁ][а-яё\-]+ Республика|Москва|Санкт-Петербург|Севастополь)", head + ", " + a)
        region = rc.clean(region.group(1).rstrip(",")) if region else ""
        m = re.search(r"\bг(?:ор)?\s*\.?\s*([А-ЯЁ][А-Яа-яё\-]+(?: [А-ЯЁ][а-яё\-]+)?)", a)
        city = m.group(1) if m else ""
        city = re.sub(r"\s+(ул|пр|пер|наб|ш)$", "", city)
        qcity = ", ".join(x for x in (city, region if region and region != city else "", "Россия") if x)
        center = geoc.geocode(qcity) if (city or region) else None
        if not center and not geoc.last_failed and region:
            center = geoc.geocode(f"{region}, Россия")
        hit = center
        pobox = bool(re.search(r"\bа/я\b|п/я", a, re.I))
        if center and not pobox and city:
            street = [x.strip() for x in a.split(",") if x.strip() and not re.fullmatch(r"\d{6}", x.strip())]
            street = [x for x in street if re.search(r"\d", x) or re.search(r"\b(ул|улица|пр|просп|пер|наб|ш|бульвар)\b", x, re.I)]
            big = city in ("Москва", "Санкт-Петербург")   # Nominatim's city point is a boundary centroid, up to ~15 km off
            qs = [", ".join(street + [x for x in (city, region, "Россия") if x])]
            m2 = re.search(r"(?:ул\.?|улица|пр-?т?\.?|проспект|пер\.?|переулок|наб\.?|ш\.?|бульвар)\s*([А-ЯЁа-яё0-9\-\. ]+?)[,\s]+(?:д\.?\s*|дом\s*)?(\d+[а-яА-Я]?)", a)
            if m2:
                qs.append(f"{m2.group(1).strip()} {m2.group(2)}, {city}")
            tol = (0.3, 0.5) if big else (0.05, 0.08)
            for q in qs:
                s_hit = geoc.geocode(q) if street else None
                if s_hit and abs(s_hit[0] - center[0]) < tol[0] and abs(s_hit[1] - center[1]) < tol[1]:
                    hit = s_hit
                    break
        if not hit or not rc.plausible("RU", *hit):
            nogeo += 1
            print(f"  {slug}: no geocode for {a!r}")
            continue
        out.append(rc.entry(name, SOURCE, "advocacy", ["Advocacy", "Information & Support", "Peer Support"],
                            "Regional branch of the All-Russian Society of Disabled People (VOI), the national organisation for people with disabilities and their families.",
                            address=a, phone=phone, website=site, lat=hit[0], lng=hit[1], external_id=f"voi:{slug}", scope="general"))
    print(f"{len(links)} pages; {bad} unusable, {disputed} skipped as occupied/annexed territory, {nogeo} without a geocode")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_voi.json"), out)
    rc.spot_check(fin, 15, fields=("name", "address", "phone"))


if __name__ == "__main__":
    main()
