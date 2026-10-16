#!/usr/bin/env python3
"""
Nordic disability-federation local branches (static HTML lists; associations without premises, so shown at municipality /
town level -- never a street):

  Denmark  DH Danske Handicaporganisationer local branches  https://handicap.dk/lokalafdelinger/find-din-afdeling   (97)
           LEV (intellectual disability) kredse               https://lev.dk/kreds                                    (~64)
           Autismeforeningen regional kredse                  https://www.autismeforeningen.dk/netvaerk-og-aktiviteter/find-din-lokale-kreds/ (12)
  Finland  Autismiliitto member associations, Kuuloliitto local associations, Nakovammaisten liitto member associations.

Branch pages and the LEV list carry board members' names, e-mail addresses and personal phone numbers: none of that is read.
Only the branch name (link text up to the first role word), the municipality / area and the federation's page URL are used.
Output: new_resources_dk_federations.json, new_resources_fi_federations.json
"""
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "small_scratch")
UA = rc.UA


def page(url, name):
    path = os.path.join(SCRATCH, name)
    if not os.path.exists(path):
        os.makedirs(SCRATCH, exist_ok=True)
        rc.download(url, path)
    return open(path, encoding="utf-8", errors="replace").read()


def anchors(t):
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', t, re.S):
        yield m.group(1), re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()


ROLE = re.compile(r"(Formand|Kontakt|Hovedstaden|Sjælland|Syddanmark|Midtjylland|Nordjylland)")
AUTISME_KREDSE = {  # slug -> (display name, town used for the point)
    "bornholm": ("Bornholm", "Rønne"), "midtsjaelland": ("Midtsjælland", "Sorø"), "midtvest": ("Midtvest", "Herning"),
    "nordjylland": ("Nordjylland", "Aalborg"), "soenderjylland": ("Sønderjylland", "Aabenraa"),
    "storkoebenhavn-nord": ("Storkøbenhavn Nord", "Lyngby"), "storstroem": ("Storstrøm", "Næstved"),
    "sydvestjylland": ("Sydvestjylland", "Esbjerg"), "trekanten": ("Trekanten", "Kolding"), "vestegnen": ("Vestegnen", "Taastrup"),
    "vestsjaelland": ("Vestsjælland", "Slagelse")}


def denmark():
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache_dk.jsonl"), countrycodes="dk")
    out, miss = [], 0

    def add(name, place, url, fed, ext, kind, scope):
        nonlocal miss
        hit = geoc.geocode(f"{place}, Denmark")
        if not hit or not rc.plausible("DK", *hit):
            miss += 1
            return
        out.append(rc.entry(name, f"{fed} local branch list", "advocacy", ["Advocacy", "Information & Support", "Peer Support"],
                            f"{kind} of {fed}. Shown at municipality level; see the branch page for contact details.",
                            address=f"{place}, Denmark", website=url, lat=hit[0], lng=hit[1], external_id=ext, scope=scope))
    seen = set()
    for href, txt in anchors(page("https://handicap.dk/lokalafdelinger/find-din-afdeling", "dh.html")):
        m = re.match(r"/lokalafdelinger/[^/]+/(dh-[^/]+)/?$", href)
        if m and m.group(1) not in seen and txt.startswith("DH "):
            seen.add(m.group(1))
            add(f"{txt} (Danske Handicaporganisationer)", txt[3:], "https://handicap.dk" + href, "DH Danske Handicaporganisationer", f"dk-dh:{m.group(1)}", "Local branch", "general")
    seen = set()
    for href, txt in anchors(page("https://lev.dk/kreds", "lev.html")):
        m = re.match(r"/kreds/([^/]+)/?$", href)
        if m and m.group(1) not in seen and txt.startswith("Lev "):
            seen.add(m.group(1))
            area = ROLE.split(txt[4:])[0].strip()      # text before "Formand" / region: the area name only
            first = re.split(r"[/,]", area)[0].strip()
            add(f"Lev {area}", first, "https://lev.dk" + href, "LEV (Landsforeningen LEV)", f"dk-lev:{m.group(1)}", "Local branch (kreds)", "general")
    for slug, (disp, town) in AUTISME_KREDSE.items():
        add(f"Autismeforeningen Kreds {disp}", town, f"https://www.autismeforeningen.dk/netvaerk-og-aktiviteter/find-din-lokale-kreds/{slug}/",
            "Autismeforeningen", f"dk-autismeforeningen:{slug}", "Regional branch (kreds)", None)
    add("Autismeforeningen Kreds Limfjord", "Skive", "https://www.kredslimfjord.dk", "Autismeforeningen", "dk-autismeforeningen:limfjord", "Regional branch (kreds)", None)
    print(f"Denmark: {len(out)} entries, {miss} without a geocode")
    return out


NON_LOCAL = re.compile(r"^(suomen|hymy|nam\b|tsau|rett|kirjon|neuropsykiatrisen|finlands|näkövammaisten|näkövammaiset|opaskoira|sokeainopetuksen|autismin kirjon)", re.I)
SPECIAL = {"Helsingin": "Helsinki", "Uudenmaan": "Uusimaa", "Länsi-Uudenmaan": "Länsi-Uusimaa", "Itä-Uudenmaan": "Itä-Uusimaa",
           "Keski-Uudenmaan": "Keski-Uusimaa", "Tampereen": "Tampere", "Jyvässeudun": "Jyväskylä", "Hämeenlinnan": "Hämeenlinna",
           # regions without a town name: shown at the regional centre
           "Ylä-Savon": "Iisalmi", "Keski-Suomen": "Jyväskylä", "Satakunnan": "Pori", "Päijät-Hämeen": "Lahti", "Vakka-Suomen": "Uusikaupunki",
           "Varkauden": "Varkaus", "Pohjois-Karjalan": "Joensuu", "Pohjois-Savon": "Kuopio", "Pohjois-Pohjanmaan": "Oulu", "Lapin": "Rovaniemi",
           "Kainuun": "Kajaani", "Pohjanmaan": "Vaasa", "Kaakkois-Suomen": "Kouvola", "Varsinais-Suomen": "Turku", "Etelä-Savon": "Mikkeli",
           "Keski-Pohjanmaan": "Kokkola", "Etelä-Pohjanmaan": "Seinäjoki", "Pohjois-Suomen": "Oulu", "Inarin-Utsjoen": "Inari", "Ylä-Karjalan": "Nurmes",
           "Kymenlaakson": "Kouvola", "Etelä-Karjalan": "Lappeenranta", "Etelä-Saimaan": "Lappeenranta", "Kanta-Hämeen": "Hämeenlinna", "Pirkanmaan": "Tampere",
           "Lahden": "Lahti", "Pudasjärven": "Pudasjärvi", "Rovaniemen": "Rovaniemi", "Virtain": "Virrat", "Turun": "Turku", "Pieksämäen": "Pieksämäki"}


def fi_places(name):
    """Candidate nominative place strings from a Finnish association name (genitive stem first word), best guess first."""
    w = re.split(r"[\s,]", re.sub(r"\b(ry|rf|r\.y\.)\b", "", name))[0].strip("-–")
    if w in SPECIAL:
        return [SPECIAL[w]]
    cands = []
    if w.endswith("n"):
        base = w[:-1]
        if base.endswith("maa") or base.endswith("maa".replace("a", "ä")) or base.endswith("lahti"):
            cands.append(base)
        if base.endswith("in") or base.endswith("en") or base.endswith("an") or base.endswith("än"):
            cands.append(base[:-2] + ("i" if base.endswith("in") else "e" if base.endswith("en") else base[-2]))
        cands.append(base)
        if base.endswith("an") or base.endswith("än"):     # Vaasan -> Vaasa
            cands.append(base[:-1] + base[-2])
    cands.append(w)
    return list(dict.fromkeys(c for c in cands if c))


FI_SOURCES = (
    ("https://autismiliitto.fi/jasenyhdistykset/", "autismiliitto.html", "Autismiliitto", None, r"(ry|rf)\b"),
    ("https://www.kuuloliitto.fi/yhdistykset-2/", "kuuloliitto.html", "Kuuloliitto", "general", r"(ry|rf)\b"),
    ("https://www.nakovammaistenliitto.fi/fi/jasenyhdistykset", "nakovammaiset.html", "Näkövammaisten liitto", "general", r"(ry|rf)\b"),
)


def finland():
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache_fi.jsonl"), countrycodes="fi")
    out, miss = [], 0
    for url, fn, fed, scope, pat in FI_SOURCES:
        t = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", "", page(url, fn), flags=re.S)
        names = []
        for m in re.finditer(r"<(a|li|h2|h3|h4|strong|p)\b[^>]*>(.*?)</\1>", t, re.S):
            x = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
            if re.search(r"\b(ry|rf)$", x, re.I) and len(x) < 90 and "@" not in x and not re.match(r"(Pj\.|sähköposti|puh)", x, re.I):
                names.append(x)
        for name in dict.fromkeys(names):
            if NON_LOCAL.match(name):
                continue
            hit = None
            for cand in fi_places(name):
                hit = geoc.geocode(f"{cand}, Finland")
                if hit and rc.plausible("FI", *hit):
                    place = cand
                    break
                hit = None
            if not hit:
                miss += 1
                continue
            slug = re.sub(r"[^a-z0-9]+", "", name.lower())[:40]
            autism = re.search(r"autis|asperger|nepsy|rett", name, re.I)
            out.append(rc.entry(name, f"{fed} member association list", "advocacy", ["Advocacy", "Information & Support", "Peer Support"],
                                f"Member association of {fed}. Shown at town / region level (taken from the association's name); see the federation's list for contact details.",
                                address=f"{place}, Finland", website=url, lat=hit[0], lng=hit[1], external_id=f"fi-fed:{fed.split()[0].lower()}:{slug}",
                                scope=None if (autism and fed == 'Autismiliitto') else "general"))
    print(f"Finland: {len(out)} entries, {miss} without a geocode")
    return out


def main():
    a = rc.finalize(os.path.join(rc.REPO, "new_resources_dk_federations.json"), denmark())
    b = rc.finalize(os.path.join(rc.REPO, "new_resources_fi_federations.json"), finland())
    rc.spot_check(a, 12, fields=("name", "address", "website"))
    rc.spot_check(b, 20, fields=("name", "address"))


if __name__ == "__main__":
    main()
