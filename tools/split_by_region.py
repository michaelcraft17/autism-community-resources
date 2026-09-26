#!/usr/bin/env python3
"""Split community_resources.json into US / Europe / World buckets for file-size management.

Derived/generated step, same relationship gen_community_data.js has to community_resources.json.
Run this after merge_new_resources.py, before gen_community_data.js.

Classification is source-first (each fetcher's `source` string reliably names its registry/
country), with an address/description/website-TLD fallback for the long tail of individually
curated entries that don't come from a bulk registry fetch.
"""
import json
import re
from collections import Counter

IN_PATH = "community_resources.json"
OUT_US = "community_resources_us.json"
OUT_EUROPE = "community_resources_europe.json"
OUT_WORLD = "community_resources_world.json"
REPORT_PATH = "tools/logs/region_split_report.txt"

US_STATE_ABBR = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA",
    "ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK",
    "OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC",
}
CA_PROVINCE_ABBR = {"AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"}
AU_STATE_ABBR = {"NSW","VIC","QLD","TAS","ACT"}  # WA/SA/NT overlap with US/Canada codes; handled via postcode shape below

EUROPEAN_COUNTRY_WORDS = [
    "ireland","irish","united kingdom","england","english","scotland","scottish","wales","welsh",
    "northern ireland","france","french","germany","german","italy","italian","spain","spanish",
    "netherlands","dutch","belgium","belgian","poland","polish","finland","finnish","sweden",
    "swedish","norway","norwegian","denmark","danish","switzerland","swiss","austria","austrian",
    "portugal","portuguese","greece","greek","czech","slovakia","slovak","slovenia","slovenian",
    "estonia","estonian","latvia","latvian","lithuania","lithuanian","ukraine","ukrainian",
    "hungary","hungarian","romania","romanian","bulgaria","bulgarian","croatia","croatian",
    "cyprus","cypriot","malta","maltese","iceland","icelandic","luxembourg",
]
WORLD_COUNTRY_WORDS = [
    "australia","australian","new zealand","canada","canadian","brazil","brazilian","mexico",
    "mexican","argentina","argentine","colombia","colombian","japan","japanese","korea","korean",
    "israel","israeli","india","indian","singapore","south africa","china","chinese","taiwan",
]

EURO_TLDS = {"ie","uk","fr","de","it","es","nl","be","pl","fi","se","no","dk","ch","at","pt",
             "gr","cz","sk","si","ee","lv","lt","ua","hu","ro","bg","hr","cy","mt","is","lu"}
WORLD_TLDS = {"au","nz","ca","br","mx","ar","co","jp","kr","il","in","sg","za","cn","tw"}

US_ZIP_RE = re.compile(r"\b([A-Z]{2})\s+\d{5}(-\d{4})?\b")
CA_POSTAL_RE = re.compile(r"\b[A-Za-z]\d[A-Za-z]\s?\d[A-Za-z]\d\b")
UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}\b")
AU_POSTCODE_NEAR_STATE_RE = re.compile(r"\b(NSW|VIC|QLD|TAS|ACT|WA|SA|NT)\s+\d{4}\b")

# Dominant source-string patterns (covers the overwhelming majority of entries by volume).
# Checked case-insensitively as substrings, longest/most-specific patterns first within each list.
US_SOURCE_PATTERNS = [
    "npi-registry", "head-start", "best-buddies", "propublica-irs", "irs exempt organizations",
    "florida division of corporations", "sibshops", "aucd-ucedd", "cpir-pti",
    "ndrn-protection-advocacy", "ecta-partc", "easterseals", "thearc", "asan-affiliate",
    "autism-society", "autism-care-network", "national resources", "state resources",
    "nationwide services", "nationwide telehealth", "eastern states", "western states",
    "regional resources", "national summer programs", "national telehealth",
    "national transition programs", "national aba providers", "national crisis services",
    "national legal advocacy", "national adult services", "california resources",
    "san jose expansion", "card", "magicalbridge.org", "aces-aba", "centria", "bluesprig",
    "trumpet", "aba-centers-america", "pbs-corp", "inbloom", "autism-partnership",
    "autism resource hub", "special-olympics", "university", "state-dds", "state-hhs",
    "state-apd", "state-opwdd", "state-ddd", "state-odp", "autism-speaks", "\"asf\"",
    "spark", "\"ari\"", "next-autism", "alpine-learning", "necc",
]
EUROPE_SOURCE_PATTERNS = [
    "france rna", "catalonia registre", "madrid registro", "england & wales charity commission",
    "canarias registro", "germany bzst", "italy runts", "cqc (uk", "czech republic ares",
    "autism-europe", "slovakia rpo", "norway bronnoysund", "belgium kbo/bce", "greece gemi",
    "netherlands anbi", "northern ireland charity commission", "cyprus register",
    "bulgaria commercial register", "estonia e-business register", "switzerland zefix",
    "finland prh", "latvia register of enterprises", "slovenia ajpes", "basque country registro",
    "national autistic society", "ambitious about autism", "autistica", "autism alliance uk",
    "research autism official site", "autism education trust", "autism together",
    "autism berkshire", "autism hampshire", "autism bedfordshire", "autism west midlands",
    "north east autism society", "autism plus", "autism anglia", "autism initiatives official",
    "autism wessex", "autism care uk", "autism concern", "autism oxford", "autism sussex",
    "autism kent", "autism wandsworth", "autism bristol", "scottish autism",
    "autism network scotland", "autism wales", "autism puzzles", "autism ni official",
    "middletown centre for autism", "peach official", "kids official", "i can official",
    "resources for autism", "dimensions uk", "united response", "mencap official",
    "special olympics gb", "special olympics northern ireland", "us in a bus", "genius within",
    "the maypole project", "cerebra official", "contact official", "sibs official",
    "nhs", "autism partnership uk", "the early intervention clinic", "acornaba",
    "carbone clinic europe", "\"i am\" official", "social skills agency", "baby speak",
    "the children's place official", "unlocking language", "london speech therapy",
    "cardiff and vale", "aneurin bevan", "hywel dda", "ndas official", "nhs greater glasgow",
    "the ot centre", "sensory uk", "belfast health", "eagle house group",
    "wakefield autism leisure club", "national portage association", "gov.uk official",
    "asperger east anglia", "greater manchester mental health", "aware official",
    "yorkshire coast families", "cambian group", "options autism", "dfn project search",
    "auticon uk", "avon and wiltshire", "devon partnership", "strathclyde autistic society",
    "pasda official",
]
WORLD_SOURCE_PATTERNS = [
    "brazil ipea", "inclusion international", "empowered kids ontario",
    "fédération québécoise", "adaptcanada.ca", "victoria disability resource centre",
    "official aspect website", "official autism queensland", "official autism sa website",
    "official autism wa website", "official amaze website", "official positive partnerships",
    "official yellow ladybugs", "official i can network", "official autism awareness australia",
    "official aeiou foundation", "official giant steps website", "official plumtree website",
    "official autism nt website", "official autism crc website",
    "official autism community network", "official marymead", "official afsa website",
    "official spectrum space website", "official autism swim website",
    "official touched by olivia", "official irabina", "official swan website",
    "official reframing autism", "official cooee speech pathology",
    "official western autistic school", "official strive for autism", "official minds and hearts",
    "official novita website", "official ku children's services", "official abiq website",
    "official learning for life autism centre", "official autism tasmania",
    "autismbc official", "act official website", "pacific autism family network",
    "canucks autism network", "family support institute of bc", "autism support network of bc",
    "popard official", "pals autism school", "square peg society", "caya bc official",
    "bc children's hospital", "island health official", "ocai official", "fcpg official",
    "aba learning centre official", "211 british columbia", "rocky mountain behaviour analysts",
    "sources bc official", "pivot point family growth centre", "branch out learning",
    "autism yukon", "yukon.ca", "act - autism community training canada",
    "nwt disabilities council", "government of nwt", "nuability official",
    "bc centre for ability", "autismbc", "autism society of central vancouver island",
    "viah official", "interior health official", "east van behavior analysis",
    "spectrum society official", "posabilities official", "zajac ranch", "autism okanagan",
    "okanagan ability centre", "variety bc official", "government of bc official",
    "set-bc official", "autism canada official", "autism alliance of canada",
    "national autism network official", "aide canada", "cnaf official",
    "sinneave family foundation", "ready willing and able", "specialisterne canada",
    "inclusion canada", "kids brain health network", "brain canada foundation",
    "child-bright network", "plan institute official", "disability alliance canada",
    "government of canada", "autism ontario official", "geneva centre for autism",
    "kerry's place", "surrey place official", "cheo official", "holland bloorview",
    "grandview kids", "lansdowne children's centre", "kidsability", "ontario government",
    "thames valley children's centre", "ongwanada official", "empower simcoe",
    "extend-a-family waterloo", "ontario autism coalition", "autism speaks canada",
    "hamilton health sciences", "sickkids", "autism services inc.", "community living toronto",
    "reena official", "accessoap official", "ontaba official", "211 ontario", "211 central",
    "on the spectrum official", "toronto autism services", "giant steps toronto",
    "spectrum works official", "ysan official", "ontario government-funded dso",
    "ottawa aba academy", "sfoa official", "service coordination support",
    "momentum aba learning centres", "bonds autism centre", "aba compass official",
    "behaviour avenues official", "aso official", "dori zener", "the possibilities clinic",
    "feel your way therapy", "summit centre official", "sunbeam developmental resource centre",
    "learning pathways developmental services", "the insight clinic", "autismedmonton",
    "autismcalgary", "autismalberta", "aafscalgary", "centreforautismab", "childrensautism.ca",
    "autism.ca", "renfreweducation", "alberta health services", "chinookautismsociety",
    "aspirechild.ca", "act community training directory", "autism society alberta",
    "pacgrandeprairie", "government of alberta", "autismresourcecentre.com",
    "autismservices.ca", "saskatchewan health authority", "regina.ecip.ca",
    "government of saskatchewan", "saskautismcenter.com", "clasaskatoon.org", "abacs.ca",
    "saskbehaviourconsulting.com", "autismmanitoba.ca", "stamant.ca", "rccinc.ca", "oheys.org",
    "manitoba theatre for young people", "asdmb.ca", "levelitupmb.ca", "government of manitoba",
    "shared health manitoba", "fanmb.ca", "varietymanitoba.com", "official fqa website",
    "autism nova scotia", "211 nova scotia", "iwk health", "hearing and speech nova scotia",
    "miriam foundation", "autisme sans limites", "giant steps montreal", "autism connections",
    "211 new brunswick", "bridge the gapp", "government of new brunswick",
    "viva therapeutic services", "upper valley autism resource centre", "caaf official website",
    "ciusss du centre-sud", "asnl official", "western health", "eastern health official",
    "autism society of pei", "government of prince edward island", "pei autistic adults",
    "government of nova scotia", "able developmental clinic", "connect autism official",
    "facebook page / autism ontario", "medicine hat news",
    "canada revenue agency official site",
]

SOURCE_RULES = [
    ("us", US_SOURCE_PATTERNS),
    ("europe", EUROPE_SOURCE_PATTERNS),
    ("world", WORLD_SOURCE_PATTERNS),
]

# Wikidata entries sometimes carry an explicit "country-scoped: X" hint in the source string.
COUNTRY_SCOPE_RE = re.compile(r"country-scoped:\s*([A-Za-z ]+)\)")

# A handful of Wikidata/GPT-Researcher entries have no address and a description too generic
# for the word-list fallback to resolve; hand-classified by name after manual lookup.
MANUAL_OVERRIDES = {
    "The Dennis J Sanders III Autism Foundation": "us",
    "Autism Research Institute": "us",
    "Autism Society of America": "us",
    "Autism Anglia": "europe",
    "Autism Rocks": "europe",
    "Alles wird gut e.V.": "europe",
}


def classify_by_source(source: str):
    m = COUNTRY_SCOPE_RE.search(source)
    if m:
        country = m.group(1).strip().lower()
        if country in EUROPEAN_COUNTRY_WORDS or country in {
            "germany", "france", "ireland", "united kingdom", "italy", "spain", "netherlands",
        }:
            return "europe"
        if country == "united states":
            return "us"
        return "world"
    s = source.lower()
    for bucket, patterns in SOURCE_RULES:
        for p in patterns:
            if p in s:
                return bucket
    return None


def classify_by_fallback(entry: dict):
    website = (entry.get("website") or "").lower()
    address = entry.get("address") or ""
    desc = (entry.get("description") or "").lower()

    # 1. Website ccTLD
    m = re.search(r"\.([a-z]{2,3})(?:/|$)", website.split("//")[-1].split("/")[0] + "/")
    if m:
        tld = m.group(1)
        if tld == "us":
            return "us"
        if tld in EURO_TLDS:
            return "europe"
        if tld in WORLD_TLDS:
            return "world"

    # 2. Address shape
    if address:
        if "usa" in address.lower() or "united states" in address.lower():
            return "us"
        m = US_ZIP_RE.search(address)
        if m and m.group(1) in US_STATE_ABBR:
            return "us"
        if CA_POSTAL_RE.search(address):
            for abbr in CA_PROVINCE_ABBR:
                if re.search(rf"\b{abbr}\b", address):
                    return "world"  # Canada
            return "world"
        if AU_POSTCODE_NEAR_STATE_RE.search(address):
            return "world"  # Australia
        if UK_POSTCODE_RE.search(address):
            return "europe"
        low = address.lower()
        for w in EUROPEAN_COUNTRY_WORDS:
            if w in low:
                return "europe"
        for w in WORLD_COUNTRY_WORDS:
            if w in low:
                return "world"

    # 3. Description text (placeless entries, e.g. Wikidata/GPT-Researcher)
    for w in EUROPEAN_COUNTRY_WORDS:
        if w in desc:
            return "europe"
    for w in WORLD_COUNTRY_WORDS:
        if w in desc:
            return "world"
    if "american" in desc or "united states" in desc:
        return "us"

    return None


def main():
    with open(IN_PATH, encoding="utf-8") as f:
        data = json.load(f)

    buckets = {"us": [], "europe": [], "world": []}
    source_bucket_counts = Counter()
    unclassified = []

    for entry in data:
        source = (entry.get("source") or "").strip()
        name = entry.get("name")
        bucket = None
        method = None
        if name in MANUAL_OVERRIDES:
            bucket = MANUAL_OVERRIDES[name]
            method = "manual"
        if bucket is None:
            bucket = classify_by_source(source)
            method = "source"
        if bucket is None:
            bucket = classify_by_fallback(entry)
            method = "fallback"
        if bucket is None:
            bucket = "world"
            method = "default"
            unclassified.append((entry.get("name"), source, entry.get("address")))
        buckets[bucket].append(entry)
        source_bucket_counts[(source, bucket, method)] += 1

    with open(OUT_US, "w", encoding="utf-8") as f:
        json.dump(buckets["us"], f, ensure_ascii=False, indent=2)
    with open(OUT_EUROPE, "w", encoding="utf-8") as f:
        json.dump(buckets["europe"], f, ensure_ascii=False, indent=2)
    with open(OUT_WORLD, "w", encoding="utf-8") as f:
        json.dump(buckets["world"], f, ensure_ascii=False, indent=2)

    print(f"Total entries: {len(data)}")
    print(f"  US:     {len(buckets['us']):>7}")
    print(f"  Europe: {len(buckets['europe']):>7}")
    print(f"  World:  {len(buckets['world']):>7}")
    print(f"  Sum:    {sum(len(v) for v in buckets.values()):>7}")
    print(f"Unclassified (defaulted to World): {len(unclassified)}")

    import os
    os.makedirs("tools/logs", exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(f"Region split report — total {len(data)}\n")
        f.write(f"US={len(buckets['us'])} Europe={len(buckets['europe'])} World={len(buckets['world'])}\n\n")
        f.write("Per-source-string bucket assignment (source | bucket | method | count):\n")
        for (source, bucket, method), count in sorted(source_bucket_counts.items(), key=lambda x: -x[1]):
            f.write(f"{count:>6} | {bucket:<7} | {method:<9} | {source}\n")
        if unclassified:
            f.write("\nEntries with no source/address/description signal (defaulted to World):\n")
            for name, source, address in unclassified:
                f.write(f"  {name!r} | source={source!r} | address={address!r}\n")

    print(f"Full per-source report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
