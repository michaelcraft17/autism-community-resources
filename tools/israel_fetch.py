#!/usr/bin/env python3
"""
Israel -- Registrar of Amutot (non-profit associations), data.gov.il datastore API (keyless):
  https://data.gov.il/api/3/action/datastore_search?resource_id=be5b7935-3922-45d4-9638-08871b17ec95

Core: registered / active amutot (not deleted) that either (a) have the secondary activity domain "assistance to people with
disabilities", or (b) match an autism / developmental-disability term in the name or stated purposes (autism, Asperger,
"on the spectrum", ADHD, Down syndrome, cerebral palsy, intellectual disability, learning disability).
Addresses (city, street, number) are geocoded with Nominatim (cached): street, then city. Output: new_resources_israel.json
"""
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "world_small_scratch")
API = "https://data.gov.il/api/3/action/datastore_search"
RES = "be5b7935-3922-45d4-9638-08871b17ec95"
SOURCE = "Israel Registrar of Amutot (data.gov.il)"
DISAB_DOMAIN = "סיוע לאנשים עם מוגבלות"
TERMS = ["אוטיז", "אוטיסט", "אספרגר", "על הרצף", "הפרעות קשב", "תסמונת דאון", "שיתוק מוחין", "מוגבלות שכלית", "לקויות למידה", "צרכים מיוחדים"]
NAME_RE = re.compile(r"אוטיז|אוטיסט|אספרגר|על הרצף|תסמונת דאון|שיתוק מוחין|מוגבלות שכלית|נכים|מוגבלות|לקויי|לקות|חירש|עיוור|ראייה|שמיעה|אקי\"ם|אלו\"ט|אלי\"ן", re.I)


def query(params):
    rows, offset = [], 0
    while True:
        q = dict(params, resource_id=RES, limit=1000, offset=offset)
        d = json.loads(rc.get(API + "?" + urllib.parse.urlencode(q), timeout=120, delay=0.5))["result"]
        rows += d["records"]
        offset += len(d["records"])
        if not d["records"] or offset >= d["total"]:
            return rows


def main():
    cache = os.path.join(SCRATCH, "il_rows.json")
    if os.path.exists(cache):
        rows = json.load(open(cache))
    else:
        os.makedirs(SCRATCH, exist_ok=True)
        rows = {}
        for r in query({"filters": json.dumps({"תחום פעילות משני": DISAB_DOMAIN})}):
            rows[r["מספר עמותה"]] = r
        for t in TERMS:
            for r in query({"q": t}):
                rows[r["מספר עמותה"]] = r
        rows = list(rows.values())
        json.dump(rows, open(cache, "w"), ensure_ascii=False)
    geoc = rc.Geocoder(os.path.join(SCRATCH, "geocode_cache_il.jsonl"), countrycodes="il")
    out, nogeo = [], 0
    for r in rows:
        if r["סטטוס עמותה"] not in ("רשומה", "פעילה"):
            continue
        he, en = rc.clean(r["שם עמותה בעברית"]), rc.clean(r["שם עמותה באנגלית"])
        he = re.sub(r"\s*\((ע~ר|ע''ר|חל~צ)\)\s*", " ", he).strip().replace("~", '"')
        en = en.replace("~", '"')
        purposes = rc.clean(r.get("מטרות עמותה"))
        domain = rc.clean(r.get("תחום פעילות משני"))
        autism = re.search(r"אוטיז|אוטיסט|אספרגר|על הרצף", he + " " + en + " " + purposes[:400])
        if not (domain == DISAB_DOMAIN or NAME_RE.search(he) or autism):
            continue
        city, street, num = rc.clean(r["כתובת - ישוב"]), rc.clean(r["כתובת - רחוב"]), rc.clean(r["כתובת - מספר דירה"])
        hit = geoc.geocode(f"{street} {num}, {city}, ישראל") if street and street != "-" else None
        hit = hit or geoc.geocode(f"{city}, ישראל")
        if not hit or not rc.plausible("IL", *hit):
            nogeo += 1
            continue
        name = en if en and re.search(r"[A-Za-z]{4}", en) and not he else (f"{he} ({en})" if en and re.search(r"[A-Za-z]{4}", en) else he)
        out.append(rc.entry(name, SOURCE, "advocacy", ["Advocacy", "Information & Support"],
                            "Registered non-profit (amuta) " + ("working with autism / developmental disability." if autism else "providing assistance to people with disabilities."),
                            address=", ".join(x for x in (f"{street} {num}".strip() if street and street != "-" else "", city, "Israel") if x),
                            lat=hit[0], lng=hit[1], external_id=f"il-amuta:{r['מספר עמותה']}", scope=None if autism and (not NAME_RE.search(he) or re.search(r"אוטיז|אוטיסט|אספרגר", he)) else "general"))
    print(f"{len(rows)} candidate rows; {len(out)} entries; {nogeo} without a geocode")
    fin = rc.finalize(os.path.join(rc.REPO, "new_resources_israel.json"), out)
    rc.spot_check(fin, 20, fields=("name", "address"))


if __name__ == "__main__":
    main()
