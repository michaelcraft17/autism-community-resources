#!/usr/bin/env python3
"""
Pull real, structured, globally-distributed autism/disability organizations from
Wikidata -- a single free API that already models these as encyclopedic entities
(name, official website, coordinates, country) rather than street-mapped POIs
(tried OpenStreetMap/Overpass first: whole-country and bbox-scoped name searches
both timed out repeatedly on the public instance -- not viable at this scale) or
LLM narration (GPT-Researcher: ~50%+ fabricated citation URLs, see verify_report.py
and WORKFLOW.md in gpt-researcher-local/).

Every hit here is required to be `instance of` one of a handful of real
organization classes (nonprofit, NGO, charity, advocacy group, foundation,
disability association) AND match "autism" in its label/text -- both enforced
server-side by Wikidata's search index, so there's no per-item hallucination risk.
The tradeoff: Wikidata only has organizations notable enough to have an entry, so
this finds national/international orgs, not small local support groups -- it's a
broad global sweep, complementary to a country-specific registry like
tools/cqc_uk_fetch.py (deep, England-only) rather than a replacement for one.

Usage:
    python3 tools/wikidata_autism_fetch.py

Writes:
    tools/wikidata_scratch/entities.json   raw fetched entity data (gitignored)
    new_resources_wikidata_global.json     final resource-schema output (repo root)
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
ENTITIES_PATH = os.path.join(SCRATCH, "entities.json")
OUT_PATH = os.path.join(REPO, "new_resources_wikidata_global.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
API = "https://www.wikidata.org/w/api.php"

# Organization classes to search within (P31 = "instance of"). Each is unioned
# with the free-text "autism" filter server-side via haswbstatement, so results
# are already restricted to real orgs, not journals/albums/people/concepts.
ORG_CLASSES = {
    "Q163740": "nonprofit organization",
    "Q79913": "non-governmental organization",
    "Q708676": "charitable organization",
    "Q431603": "advocacy group",
    "Q10517154": "disability association",
    "Q157031": "foundation",
}

SEARCH_TERM = "autism"


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


def search_qids():
    qids = set()
    for qid, label in ORG_CLASSES.items():
        offset = 0
        while True:
            data = api_get({
                "action": "query", "list": "search",
                "srsearch": f"haswbstatement:P31={qid} {SEARCH_TERM}",
                "srlimit": 50, "sroffset": offset, "format": "json",
            })
            hits = data.get("query", {}).get("search", [])
            for h in hits:
                qids.add(h["title"])
            total = data.get("query", {}).get("searchinfo", {}).get("totalhits", 0)
            print(f"  [{label}] offset {offset}: {len(hits)} hits (total for class: {total})")
            offset += 50
            if "continue" not in data or offset >= total:
                break
    print(f"\nTotal unique QIDs found across all classes: {len(qids)}")
    return sorted(qids)


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


def build_resources(entities):
    resources = []
    for qid, entity in entities.items():
        label = entity.get("labels", {}).get("en", {}).get("value")
        if not label:
            continue
        description = entity.get("descriptions", {}).get("en", {}).get("value", "")
        website = extract_claim_value(entity, "P856")
        coord = extract_claim_value(entity, "P625")

        entry = {
            "name": label,
            "type": infer_type(description),
            "source": f"Wikidata (structured global dataset), {qid}",
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
    print("Searching Wikidata for autism-related organizations across "
          f"{len(ORG_CLASSES)} org classes...")
    qids = search_qids()

    print("\nFetching full entity details...")
    entities = fetch_entities(qids)
    with open(ENTITIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entities, f, indent=2, ensure_ascii=False)

    resources = build_resources(entities)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_website = sum(1 for r in resources if r.get("website"))
    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_website} have a website, {with_coords} have coordinates")


if __name__ == "__main__":
    main()
