#!/usr/bin/env python3
"""
Norway: disability organisations and services from the Bronnoysund Register Centre's Enhetsregisteret bulk files
(keyless, daily, gzip CSV; NLOD licence):

    https://data.brreg.no/enhetsregisteret/api/underenheter/lastned/csv     sub-units (physical establishments)
    https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv          legal units
  (send  Accept: application/vnd.brreg.enhetsregisteret.<underenhet|enhet>.v2+gzip;charset=UTF-8 )

Supersedes the name-search-only tools/norway_brreg_fetch.py. Core selection (see HANDOFF.md for the rationale):
  * SN2025 code (naeringskode 1-3) 85.202 special schools, 85.691 PPT, 85.692 special-education competence centres,
    87.104 respite homes, 87.202 housing for people with intellectual disability, 88.104 BPA, 88.105 respite,
    88.102 day activity, 88.993 sheltered work (VTA)
  * name hits (autism, asperger, funksjonshem, utviklingshem, dov/hørsel/syn terms, ADHD, Down, CP, habilitering,
    avlastning, BPA, NFU, Statped, ...) on both files; purpose text only for associations (FLI) and foundations (STI)
Excluded: sole proprietorships (ENK; names are people), bankrupt / dissolving / closed units, municipalities and
counties as legal units (their sub-units are the sites), construction/property/trade codes on name hits.
No daglig leder / role data is read. The broad codes (87.300, 88.101, 86.950, 86.930; ~11k rows) are NOT built here.

Locations: street addresses are geocoded with Kartverket (cached). Housing (87.104, 87.202) is people's homes, so it is
NOT pinned: one entry per operator and municipality at the municipality's representative point. Rows whose organisation
number is in new_resources_nsr.json are skipped (NSR has better coordinates).

Writes new_resources_norway_brreg.json; the 106 earlier name-search rows have no ids, so the merge's name+city rule
removes the overlap.
"""
import csv
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

csv.field_size_limit(10 ** 9)
SCRATCH = os.path.join(rc.REPO, "tools", "norway_brreg2_scratch")
SOURCE = "Norway Bronnoysund Register Centre (Enhetsregisteret) - official national entity registry"
CODE_INFO = {   # code -> (type, services, description)
    "85.202": ("education", ["Special Education"], "Special school (spesialskole)"),
    "85.691": ("education", ["Special Education", "Psychological Counselling"], "Educational and psychological counselling service (PPT)"),
    "85.692": ("education", ["Special Education", "Information & Support"], "Special-education competence centre"),
    "87.104": ("social", ["Residential & Social Care", "Respite Care"], "Respite home"),
    "87.202": ("social", ["Residential & Social Care"], "Housing for people with intellectual disability"),
    "88.104": ("social", ["Personal Assistance"], "User-directed personal assistance (BPA)"),
    "88.105": ("social", ["Respite Care"], "Respite care"),
    "88.102": ("social", ["Day Activities"], "Day activity for people with disabilities"),
    "88.993": ("social", ["Employment Support"], "Sheltered work (VTA) for people with disabilities"),
}
HOUSING = {"87.104", "87.202"}
NAME_RE = re.compile(
    r"(?<![a-zæøå])autis|asperger|funksjonshem|funksjonsnedsett|utviklingshem|handikap|\bdøv(e|blind|eforbund|es|eskole)|tunghør|hørselshem|"
    r"svaksynt|synshem|\bblinde(s|forbund|forbundet)?\b|cerebral\s*parese|down\s*syndrom|\badhd\b|tourette|epilepsi|ryggmargsbrokk|muskelsyk|"
    r"dysleksi|spesialpedagog|(?<!re)habiliter|avlastning|\bbpa\b|rullestol|parasport|special olympics|tegnspråk|afasi|hjerneskade|\bnfu\b|statped|\bsigno\b",
    re.I)
PURPOSE_NO = re.compile(r"hjerte|lunge|kreft|narkotika|\brus\b|rusmiddel", re.I)
BAD_CODE_PREFIX = ("41", "42", "43", "68", "71", "37", "46", "47")
SKIP_FORMS = {"ENK", "KOMM", "FYLK", "STAT", "FKF", "KF", "IKJP"}
ASSOC_FORMS = {"FLI", "STI"}


def rows(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def codes(r):
    return [c for c in (r.get("naeringskode1.kode"), r.get("naeringskode2.kode"), r.get("naeringskode3.kode")) if c]


def title(s):
    s = rc.clean(s)
    return s.title() if s.isupper() else s


def main():
    nsr = {e["external_id"] for e in json.load(open(os.path.join(rc.REPO, "new_resources_nsr.json")))} \
        if os.path.exists(os.path.join(rc.REPO, "new_resources_nsr.json")) else set()
    hits, parents, parent_form = {}, {}, {}   # orgnr -> (row, kind, why)

    for kind, fn, pre in (("sub", "underenheter.csv.gz", "beliggenhetsadresse"), ("legal", "enheter.csv.gz", "forretningsadresse")):
        n = 0
        for r in rows(os.path.join(SCRATCH, fn)):
            n += 1
            org, form = r["organisasjonsnummer"], r["organisasjonsform.kode"]
            if kind == "legal":
                parents[org] = r["navn"]
                parent_form[org] = form
                if r.get("konkurs") == "true" or r.get("underAvvikling") == "true" or r.get("underTvangsavviklingEllerTvangsopplosning") == "true":
                    continue
            elif r.get("nedleggelsesdato"):
                continue
            if form in SKIP_FORMS or f"no-org:{org}" in nsr:
                continue
            cs = codes(r)
            code = next((c for c in cs if c in CODE_INFO), None)
            why = f"code {code}" if code else None
            if not why and NAME_RE.search(r["navn"]):
                if not any(c.startswith(BAD_CODE_PREFIX) for c in cs):
                    why = "name"
            # purpose-text hits (foundations / associations whose statutes merely mention a disability word) are not
            # used: they brought in sports clubs, legacy foundations and gaming groups.
            if why:
                hits[org] = (r, kind, why, code, pre)
        print(f"{fn}: {n} rows scanned, {len(hits)} hits so far")

    # sub-units of sole proprietorships are people's businesses (names like "Tegnspråktolk <Person>"): drop them
    for org in [o for o, h in hits.items() if h[1] == "sub" and parent_form.get(h[0].get("overordnetEnhet")) in SKIP_FORMS]:
        del hits[org]
    # a legal unit that shares its address with one of its own hit sub-units is the same place
    sub_addr = {}
    for org, (r, kind, why, code, pre) in hits.items():
        if kind == "sub":
            sub_addr.setdefault(r["overordnetEnhet"], set()).add((r["beliggenhetsadresse.adresse"].lower(), r["beliggenhetsadresse.postnummer"]))
    kv = rc.Kartverket(os.path.join(SCRATCH, "kartverket_cache.jsonl"))
    entries, housing = [], {}
    dropped_parent = nogeo = 0
    for org, (r, kind, why, code, pre) in hits.items():
        addr1, post, poststed, kommune, knr = (r[f"{pre}.adresse"], r[f"{pre}.postnummer"], r[f"{pre}.poststed"],
                                               r[f"{pre}.kommune"], r[f"{pre}.kommunenummer"])
        if kind == "legal" and (addr1.lower(), post) in sub_addr.get(org, set()):
            dropped_parent += 1
            continue
        if code in HOUSING:
            op_org = r["overordnetEnhet"] if kind == "sub" and r.get("overordnetEnhet") else org
            h = housing.setdefault((op_org, knr), {"op": title(parents.get(op_org) or r["navn"]), "muni": title(kommune), "n": 0, "code": code})
            h["n"] += 1
            continue
        if re.match(r"\s*(c/o|v/)\s", addr1, re.I):   # care-of a named person: a private address, never published
            nogeo += 1
            continue
        hit = kv.address(addr1, post, knr)
        if not hit or not rc.plausible("NO", *hit):
            nogeo += 1
            continue
        if code:
            typ, services, kind_txt = CODE_INFO[code]
            desc = f"{kind_txt}, {title(kommune)}."
        else:
            form = r["organisasjonsform.kode"]
            typ = "advocacy" if form in ASSOC_FORMS else "general_support"
            services = ["Advocacy", "Information & Support"] if typ == "advocacy" else ["Information & Support"]
            what = "Local unit" if kind == "sub" else {"FLI": "Association", "STI": "Foundation", "AS": "Company", "ASA": "Company", "KS": "Company", "ANS": "Company", "DA": "Company", "SA": "Cooperative", "NUF": "Company"}.get(r["organisasjonsform.kode"], rc.clean(r["organisasjonsform.beskrivelse"]))
            desc = f"{what} in {title(kommune)} with a disability-related name."
        address = ", ".join(x for x in (rc.clean(addr1), f"{post} {title(poststed)}".strip(), "Norway") if x)
        phone = rc.clean(r.get("telefon")) or rc.clean(r.get("mobil"))
        entries.append(rc.entry(title(r["navn"]), SOURCE, typ, services, desc, address=address, phone=phone or None,
                                website=rc.clean_url(r.get("hjemmeside")), lat=hit[0], lng=hit[1], external_id=f"no-org:{org}",
                                scope=None if re.search(r"(?<![a-zæøå])autis|asperger", r["navn"], re.I) else "general"))
    nohome = 0
    for (op, knr), h in housing.items():
        hit = kv.municipality(knr)
        if not hit:
            nohome += 1
            continue
        what = "Respite homes" if h["code"] == "87.104" else "Housing"
        n = f"{h['n']} units" if h["n"] > 1 else "1 unit"
        entries.append(rc.entry(f"{h['op']} - {what.lower()} for people with disabilities, {h['muni']}", SOURCE, "social",
                                ["Residential & Social Care"] + (["Respite Care"] if h["code"] == "87.104" else []),
                                f"{what} for people with disabilities ({n}) run by {h['op']} in {h['muni']}. Shown at municipality level; individual homes are not published here.",
                                address=f"{h['muni']}, Norway", lat=hit[0], lng=hit[1], external_id=f"no-housing:{op}:{knr}", scope="general"))
    print(f"{len(hits)} hits: {dropped_parent} legal units dropped (same address as their sub-unit), {nogeo} without a geocode, "
          f"{sum(h['n'] for h in housing.values())} housing units collapsed into {len(housing)} municipality entries ({nohome} without a geocode)")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_norway_brreg.json"), entries)
    rc.spot_check(out, 30, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
