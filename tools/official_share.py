#!/usr/bin/env python3
"""Share of listings whose source is a government / regulator register or open-data file (the landing page's
"from official registries" stat). Everything else is a published directory of a nonprofit, network or university.
Conservative: a source is official only if it is not in NON_OFFICIAL and not a bare lowercase key (the national-nonprofit
scrapes use keys like best-buddies). propublica-irs-autism counts as non-official (a third-party repackaging of IRS data).
Usage: python3 tools/official_share.py   (prints the percentage; copy into TRUST_STATS in index.html)"""
import collections, glob, json, os, re
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NON_OFFICIAL = re.compile(
    r"^(national resources|nationwide services|state resources)\b|member|directory \(|branch|local branch|regional (associations|organisations)|"
    r"affiliate|full member listing|federation|\(2023 pdf\)|empowered kids|autism society|^LEV |Landsforeningen|Kuuloliitto|Danske Handicap|"
    r"Behindertenrat|Russian Society of the Deaf|VOI \(|Autismo Espa|Federal Resource Centre for ASD", re.I)
c = collections.Counter()
for f in glob.glob(os.path.join(REPO, "data", "*", "*.json")):
    for e in json.load(open(f, encoding="utf-8")):
        s = e.get("source", "") or ""
        official = bool(re.search(r"\.gov\b|gov\.ba|datosabiertos|data\.gouv", s)) or not (NON_OFFICIAL.search(s) or re.fullmatch(r"[a-z0-9-]+", s) and s != "npi-registry" and s != "head-start")
        c[(official, s)] += 1
tot = sum(c.values()); off = sum(n for (o, _), n in c.items() if o)
print(f"{off}/{tot} = {100*off/tot:.1f}% official")
for (o, s), n in sorted(c.items(), key=lambda x: -x[1]):
    if not o and n >= 15: print("  non-official", n, s[:90])
