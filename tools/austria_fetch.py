#!/usr/bin/env python3
"""
Austria (new country shard AT) -- open-data parts of round 7:
  AT1 Statistik Austria "Schulen in Oesterreich" WFS (special schools, with point coordinates; CC BY 4.0)
  AT2 Vienna open data: school addresses by SKZ + hospital outpatient clinics (AMBULANZOGD) for developmental needs
  AT3 NOe Schulfuehrer (2013, stale) used only for street addresses of AT1 rows by SKZ
  AT4 Upper Austria Chancengleichheitsgesetz services (ChG_Arbeit / ChG_Wohnen / ChG_PSB, CC BY 4.0)
  AT5 Burgenland disability facilities (March 2017 list)
Core only: Sonderschulen and special schools filed under other types; inclusive mainstream schools are broad and not built.
Privacy: group homes (ChG Wohnen, Burgenland "Wohngemeinschaft") are people's homes, so they are shown at municipality
level (PLZ + Ort geocode, no street); Burgenland e-mails and the NOe school mailbox are not kept. NEBA and the Behindertenrat
member list are HTML scrapes and are not in this file. Inputs live in tools/austria_scratch/ (see FILES). Nominatim, 1 req/s.
Output: new_resources_austria.json
"""
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "austria_scratch")
FILES = {
    "schulen.json": "https://www.statistik.at/gs-open/ATLAS_SCHULE_OPEN/ows?service=WFS&version=2.0.0&request=GetFeature&typeNames=ATLAS_SCHULE_OPEN:SCHULEN_2024_25&outputFormat=application/json&srsName=EPSG:4326",
    "wien_schulen.json": "https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0&typeName=ogdwien:SCHULEOGD&srsName=EPSG:4326&outputFormat=json",
    "wien_amb.json": "https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0&typeName=ogdwien:AMBULANZOGD&srsName=EPSG:4326&outputFormat=json",
    "noe.csv": "https://open-data.noe.gv.at/ogd-data/LSR/schulen_noe.csv",
    "ooe_Arbeit.csv": "https://e-gov.ooe.gv.at/at.gv.ooe.ogd2-citi/api/file/_4lUFKmRYbCMyUhyf37kqw/ChG_Arbeit.csv",
    "ooe_Wohnen.csv": "https://e-gov.ooe.gv.at/at.gv.ooe.ogd2-citi/api/file/rNZGR0mZ3tTatWoq7jFPsQ/ChG_Wohnen.csv",
    "ooe_PSB.csv": "https://e-gov.ooe.gv.at/at.gv.ooe.ogd2-citi/api/file/Oit17wo7bmDD5BnAfZ3Jlw/ChG_PSB.csv",
    "bgld.csv": "https://intranet.burgenland.at//fileadmin-ogd/user_upload/Abteilung_6/Gesamtuebersicht_BEHINDERTENEINRICHTUNGN_Maerz_2017.csv",
}
SPECIAL = re.compile(r"sonderschule|sondererziehung|sonderp.dagog|blind|sehbehindert|geh.rlos|schwerh.rig|heilst.tten|schwerstbehindert|"
                     r"sprachgest.rt|komit|odilien|heilp.dagog", re.I)
INCLUSIVE = re.compile(r"montessori|freiraum|holly|schubert|lernwerkstatt|integrativ|waldorf", re.I)
NOT_SPECIAL_TYPE = {"GKS", "BMHSP", "BSTAT"}
CLINIC = re.compile(r"adhs|entwicklung(?!s(geschlecht|st))|entwicklung$|neuro?p.d|down syndrom|mehrfachbehinder|behinderten ambulanz|"
                    r"sehbehinderten|cerebral|zerebral|phoniatr|allgemeine ambulanz \(terminambulanz\)", re.I)
CLINIC_BAD = re.compile(r"geschlechtsentwicklung", re.I)
SRC_SCHOOL = "Austria Statistik Austria schools layer (special schools)"
SRC_CLINIC = "Austria Vienna open data hospital outpatient clinics"
SRC_OOE = "Austria Upper Austria Chancengleichheitsgesetz services"
SRC_BGLD = "Austria Burgenland disability facilities list"


def fetch_all():
    for f, u in FILES.items():
        p = os.path.join(SCRATCH, f)
        if not os.path.exists(p):
            rc.download(u, p)


def rd(f, enc="cp1252"):
    return list(csv.DictReader(open(os.path.join(SCRATCH, f), encoding=enc, errors="replace"), delimiter=";"))


def sk(s):
    return re.sub(r"\D", "", str(s or ""))


def web(u):
    u = rc.clean(u)
    if not u:
        return None
    return rc.clean_url(u if u.lower().startswith("http") else "http://" + u)


def tidy(s):
    return re.sub(r"\s+", " ", rc.clean(s)).strip(" ,")


def main():
    fetch_all()
    rc.STATUS["input"] = "Statistik Austria SCHULEN_2024_25, Vienna WFS, OOe ChG, Burgenland 2017"
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache.jsonl"), countrycodes="at")
    out = []

    # --- AT1/AT2/AT3 special schools ---
    wien = {}
    for f in json.load(open(os.path.join(SCRATCH, "wien_schulen.json")))["features"]:
        p = f["properties"]
        wien[sk(p["SKZ"])] = p
    noe = {sk(r["skz"]): r for r in rd("noe.csv")}
    nschool = nbroad = 0
    for f in json.load(open(os.path.join(SCRATCH, "schulen.json")))["features"]:
        p, typ = f["properties"], f["properties"]["TYP"]
        name = tidy(p["BEZEICHNUNG"])
        if typ in NOT_SPECIAL_TYPE or re.search(r"sozialbetreuung|krankenpflege", name, re.I):
            continue
        if not (typ == "SS" or SPECIAL.search(name)):
            continue
        if typ != "SS" and INCLUSIVE.search(name):
            nbroad += 1
            continue
        lng, lat = f["geometry"]["coordinates"]
        if not rc.plausible("AT", lat, lng):
            continue
        skz = sk(p["SKZ"])
        street, phone, site = None, None, None
        if skz in wien:
            w = wien[skz]
            street = re.sub(r"^\d+\.,\s*", "", w.get("ADRESSE") or "") + ", Wien"
            phone, site = tidy(w.get("TELEFON")), web(w.get("WEBLINK1"))
        elif skz in noe:
            n = noe[skz]
            street = ", ".join(x for x in (tidy(n["strasse"]), f"{tidy(n['plz'])} {tidy(n['ort'])}".strip()) if x)
            phone, site = tidy(n["tel"]), web(n["url_hp"])
        addr = street or f"{p['GEMNAME']}"
        shown = name if (name.lower() != "allgemeine sonderschule") else f"Allgemeine Sonderschule {p['GEMNAME']}"
        out.append(rc.entry(shown, SRC_SCHOOL, "education", ["Special education", "Education"],
                            f"Austrian special school (Sonderschule), school code {p['SKZ']}, {p['GEMNAME']}.",
                            address=addr + ", Österreich", phone=phone or None, website=site, lat=lat, lng=lng,
                            external_id=f"at-skz:{p['SKZ']}", scope="general"))
        nschool += 1

    # --- AT2 Vienna clinics ---
    nclin = 0
    for f in json.load(open(os.path.join(SCRATCH, "wien_amb.json")))["features"]:
        p = f["properties"]
        t = f"{p.get('ABTEILUNG') or ''} {p.get('BEZEICHNUNG') or ''}"
        if not CLINIC.search(t) or CLINIC_BAD.search(t) or not f.get("geometry"):
            continue
        lng, lat = f["geometry"]["coordinates"][:2]
        if not rc.plausible("AT", lat, lng):
            continue
        autism = bool(re.search(r"adhs|entwicklung", t, re.I))
        hosp = tidy(re.sub(r"<[^>]+>", " ", p.get("KRANKENHAUS_BEZEICHNUNG") or ""))
        dep = tidy(re.sub(r"<[^>]+>", " ", p.get("ABTEILUNG") or ""))
        ph = tidy(p.get("TELEFON")).replace("(+43 1)", "").strip()
        out.append(rc.entry(tidy(p["BEZEICHNUNG"]) + f" ({hosp})", SRC_CLINIC, "medical", ["Medical care", "Diagnosis & Assessment"],
                            f"Vienna hospital outpatient clinic: {dep}.", address=re.sub(r"^\d+\.,\s*", "", p.get("ADRESSE") or "") + ", Wien, Österreich",
                            phone=ph if len(ph) < 30 else None, website=web(p.get("WEBLINK1")), lat=lat, lng=lng,
                            external_id=f"at-wien-amb:{p['OBJECTID']}", scope=None if autism else "general"))
        nclin += 1

    # --- AT4 Upper Austria ---
    nooe = nogeo = 0
    for fname, kind in (("ooe_Arbeit.csv", "Arbeit"), ("ooe_Wohnen.csv", "Wohnen"), ("ooe_PSB.csv", "PSB")):
        for r in rd(fname):
            if kind == "PSB":
                name, op, plz, ort, st = r["Einrichtung"], r["Träger"], r["PLZ"], r["ORT"], f"{r['STRASSE']} {r['Hnr.']}"
                eid, art = f"psb-{plz.strip()}-{rc.clean(name)}", "Psychosocial counselling"
            else:
                name, op, plz, ort, st = r["Leistungserbringer"], r["Rechtstraeger"], r["PLZ"], r["Ort"], r["Straße"]
                eid, art = tidy(r["ENR"]) or f"{plz.strip()}-{rc.clean(name)}", r["Leistungsart"]
            plz, ort, st = tidy(plz), tidy(ort), tidy(st)
            if not tidy(name):  # the Wohnen file ends with a blank row (ENR "-", no name or address)
                continue
            home = kind == "Wohnen"
            q = f"{plz} {ort}, Österreich" if home else f"{st}, {plz} {ort}, Österreich"
            hit = geoc.geocode(q) or geoc.geocode(f"{plz} {ort}, Österreich")
            if not hit or not rc.plausible("AT", *hit):
                nogeo += 1
                continue
            if kind == "Arbeit":
                svc, typ = ["Day programs", "Employment"], "social"
            elif kind == "Wohnen":
                svc, typ = ["Supported living", "Residential & Social Care"], "social"
            else:
                svc, typ = ["Counselling", "Information & Support"], "general_support"
            out.append(rc.entry(tidy(name), SRC_OOE, typ, svc,
                                f"Upper Austria disability service under the Chancengleichheitsgesetz ({art}), operated by {tidy(op)}.",
                                address=(f"{plz} {ort}" if home else f"{st}, {plz} {ort}") + ", Österreich", lat=hit[0], lng=hit[1],
                                external_id=f"at-ooe:{kind}:{eid}", scope="general"))
            nooe += 1

    # --- AT5 Burgenland ---
    nb = 0
    for i, line in enumerate(csv.reader(open(os.path.join(SCRATCH, "bgld.csv"), encoding="cp1252", errors="replace"), delimiter=";")):
        if i == 0 or len(line) < 9 or not line[1].strip():
            continue
        name, st, plz, ort, op = tidy(line[1]), tidy(line[2]), tidy(line[3]), tidy(line[4]), tidy(line[5])
        phone = tidy(line[10]) if len(line) > 10 else ""
        home = bool(re.search(r"wohn|wg\b|gemeinschaft", name, re.I))
        hit = geoc.geocode(f"{plz} {ort}, Österreich" if home else f"{st}, {plz} {ort}, Österreich") or geoc.geocode(f"{plz} {ort}, Österreich")
        if not hit or not rc.plausible("AT", *hit):
            nogeo += 1
            continue
        out.append(rc.entry(name, SRC_BGLD, "social", ["Supported living" if home else "Day programs", "Residential & Social Care"],
                            f"Burgenland disability facility (list dated March 2017), operated by {op}.",
                            address=(f"{plz} {ort}" if home else f"{st}, {plz} {ort}") + ", Österreich", phone=phone or None,
                            lat=hit[0], lng=hit[1], external_id=f"at-bgld:{plz}-{rc.clean(name)}", scope="general"))
        nb += 1

    print(f"schools {nschool} (+{nbroad} inclusive skipped as broad); Vienna clinics {nclin}; Upper Austria {nooe}; Burgenland {nb}; {nogeo} without a geocode")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_austria.json"), out)
    rc.spot_check(fin, 25, fields=("name", "address", "type"))


if __name__ == "__main__":
    main()
