#!/usr/bin/env python3
"""
Country-scoped variant of wikidata_autism_fetch.py -- same official, structured
Wikidata source (real orgs, `instance of` one of a handful of organization
classes, server-side "autism"-family text match, no per-item hallucination
risk), but additionally constrained to P17 (country) for a specific list of
countries, and searched with native-language autism terms as well as English.

Why a separate script instead of a country flag on the original: the original
already ran as an unscoped global sweep (merged in 70ed78b) -- re-running it
finds the same entities again (deduped away downstream). This script targets
countries that sweep likely under-covered because their organizations' labels
aren't in English, per HANDOFF.md's "Natural next steps" (non-English autism-
root search terms for non-Latin-script / non-English countries).

Usage:
    python3 tools/wikidata_country_fetch.py

Writes:
    tools/wikidata_scratch/entities_countries.json   raw fetched entity data (gitignored)
    new_resources_wikidata_countries.json            final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(REPO, "tools", "wikidata_scratch")
os.makedirs(SCRATCH, exist_ok=True)
ENTITIES_PATH = os.path.join(SCRATCH, "entities_countries.json")
OUT_PATH = os.path.join(REPO, "new_resources_wikidata_countries.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
API = "https://www.wikidata.org/w/api.php"

ORG_CLASSES = {
    "Q163740": "nonprofit organization",
    "Q79913": "non-governmental organization",
    "Q708676": "charitable organization",
    "Q431603": "advocacy group",
    "Q10517154": "disability association",
    "Q157031": "foundation",
}

# P17 (country) QID -> (label, native-language autism-root search terms that
# uniquely signal that country; Sweden/Romania have none listed since their
# native "autism" spelling matches English closely enough that it relies
# entirely on the P17 claim check against the generic "autism" sweep below).
COUNTRIES = {
    "Q183": ("Germany", ["autismus", "autist"]),
    "Q159": ("Russia", ["аутизм", "аутист"]),
    "Q34": ("Sweden", []),
    "Q148": ("China", ["自闭症", "孤独症"]),
    "Q37": ("Lithuania", ["autizmas"]),
    # 2026-09-24 round: countries with exactly one prior listing (the
    # Autism-Europe PDF's national umbrella org) where the country's own
    # government registry is unreachable from this sandbox (Denmark, Germany
    # re-checked) or has no bulk/search API at all (the rest) -- see
    # HANDOFF.md for what was tried and ruled out for each.
    "Q35": ("Denmark", ["autisme"]),
    "Q224": ("Croatia", ["autizam"]),
    "Q41": ("Greece", ["αυτισμός"]),
    "Q189": ("Iceland", ["einhverfa"]),
    "Q32": ("Luxembourg", ["autisme", "autismus"]),
    "Q403": ("Serbia", ["аутизам", "autizam"]),
    "Q214": ("Slovakia", ["autizmus"]),
    "Q219": ("Bulgaria", ["аутизъм"]),
    "Q229": ("Cyprus", ["αυτισμός"]),
    "Q218": ("Romania", []),
    "Q43": ("Turkey", ["otizm"]),
    "Q212": ("Ukraine", ["аутизм", "аутизму"]),
    "Q228": ("Andorra", ["autisme"]),
}


def api_get(params, max_retries=5):
    url = API + "?" + urllib.parse.urlencode(params)
    delay = 2
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                print(f"  rate limited, backing off {delay}s...")
                time.sleep(delay)
                delay *= 2
                continue
            raise
        finally:
            time.sleep(1.2)  # be a good citizen on the shared free API regardless of outcome


def run_search(term, org_qid):
    hits_found = []
    offset = 0
    while True:
        data = api_get({
            "action": "query", "list": "search",
            "srsearch": f"haswbstatement:P31={org_qid} {term}",
            "srlimit": 50, "sroffset": offset, "format": "json",
        })
        hits = data.get("query", {}).get("search", [])
        hits_found.extend(h["title"] for h in hits)
        total = data.get("query", {}).get("searchinfo", {}).get("totalhits", 0)
        if hits:
            print(f"  ['{term}'/{org_qid}] offset {offset}: {len(hits)} hits (total: {total})")
        offset += 50
        if "continue" not in data or offset >= total:
            break
    return hits_found


def search_qids():
    # P17 (country) is often unset even on real, verifiable org entries, so
    # requiring it server-side undercounts badly -- confirmed empirically:
    # doing that first found only 5 QIDs total across all 5 countries. Two
    # passes instead: (1) native-language autism-root terms are themselves a
    # strong, near-unambiguous country signal (German "autismus", Russian
    # "аутизм"/"аутист", Chinese "自闭症"/"孤独症", Lithuanian "autizmas");
    # (2) a generic "autism" sweep (needed for Sweden, which has no
    # distinguishing native term) gets cross-checked against each hit's own
    # P17 claim after fetching, in build_resources.
    native_hits = {}  # qid -> country_qid, unambiguous by construction
    for country_qid, (country_label, native_terms) in COUNTRIES.items():
        for org_qid in ORG_CLASSES:
            for term in native_terms:
                for qid in run_search(term, org_qid):
                    native_hits[qid] = country_qid

    generic_hits = set()
    for org_qid in ORG_CLASSES:
        generic_hits.update(run_search("autism", org_qid))

    all_qids = sorted(set(native_hits) | generic_hits)
    print(f"\n{len(native_hits)} QIDs matched natively (unambiguous country), "
          f"{len(generic_hits)} from generic 'autism' sweep (P17 checked after fetch), "
          f"{len(all_qids)} unique total")
    return all_qids, native_hits


def fetch_entities(qids):
    entities = {}
    for i in range(0, len(qids), 50):
        batch = qids[i:i + 50]
        data = api_get({
            "action": "wbgetentities", "ids": "|".join(batch),
            "props": "labels|descriptions|claims", "languages": "en", "format": "json",
        })
        entities.update(data.get("entities", {}))
        print(f"  fetched entity details {i + len(batch)}/{len(qids)}")
    return entities


def extract_claim_value(entity, prop):
    claims = entity.get("claims", {}).get(prop, [])
    if not claims:
        return None
    try:
        return claims[0]["mainsnak"]["datavalue"]["value"]
    except (KeyError, IndexError):
        return None


TYPE_KEYWORDS = [
    (("research", "scientific", "study"), "medical"),
    (("therapy", "treatment", "clinic", "clinical", "hospital"), "medical"),
    (("school", "education", "training"), "education"),
    (("advocacy", "rights", "policy"), "advocacy"),
    (("social", "peer", "community group", "meetup"), "social"),
]


def infer_type(description):
    d = (description or "").lower()
    for keywords, t in TYPE_KEYWORDS:
        if any(k in d for k in keywords):
            return t
    return "general_support"


def resolve_country(qid, entity, native_hits):
    """Prefer the entity's own P17 (country) claim when it names one of our
    5 targets; otherwise fall back to the native-search-term tag, which is
    unambiguous by construction. Returns None if neither applies -- e.g. a
    generic 'autism' hit whose P17 points elsewhere, meaning it isn't one of
    our target countries and belongs to the original global sweep, not here."""
    country_label_by_qid = {qid_: label for qid_, (label, _) in COUNTRIES.items()}
    p17 = extract_claim_value(entity, "P17")
    if isinstance(p17, dict):
        p17_qid = p17.get("id")
        if p17_qid in country_label_by_qid:
            return country_label_by_qid[p17_qid]
        if p17_qid:
            return None  # has a country claim, and it's not one of our targets
    return country_label_by_qid.get(native_hits.get(qid))


def build_resources(entities, native_hits):
    resources = []
    for qid, entity in entities.items():
        label = entity.get("labels", {}).get("en", {}).get("value")
        if not label:
            continue
        country = resolve_country(qid, entity, native_hits)
        if not country:
            continue  # not one of our 5 target countries; leave it to the global sweep

        description = entity.get("descriptions", {}).get("en", {}).get("value", "")
        website = extract_claim_value(entity, "P856")
        coord = extract_claim_value(entity, "P625")

        entry = {
            "name": label,
            "type": infer_type(description),
            "source": f"Wikidata (structured global dataset, country-scoped: {country}), {qid}",
            "services": ["Information & Support"],
            "description": description[0].upper() + description[1:] + "." if description else f"{label} -- see Wikidata for details.",
        }
        if website:
            entry["website"] = website
        if coord:
            entry["coordinates"] = {"lat": coord["latitude"], "lng": coord["longitude"]}
        else:
            entry["placeless"] = True
        resources.append(entry)
    return resources


def main():
    print(f"Searching Wikidata for autism-related organizations in {len(COUNTRIES)} "
          f"target countries ({', '.join(l for l, _ in COUNTRIES.values())})...")
    qids, native_hits = search_qids()

    print("\nFetching full entity details...")
    entities = fetch_entities(qids)
    with open(ENTITIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entities, f, indent=2, ensure_ascii=False)

    resources = build_resources(entities, native_hits)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_website = sum(1 for r in resources if r.get("website"))
    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_website} have a website, {with_coords} have coordinates")


if __name__ == "__main__":
    main()
