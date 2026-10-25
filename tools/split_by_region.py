#!/usr/bin/env python3
"""Split community_resources.json into per-region shards (one JSON file per US state / European
country, plus one World file) under data/, and write data/manifest.json for the app.

The shards are the committed source of truth (each stays far below GitHub's 50MB warning);
community_resources.json is a local working file that tools/join_regions.py rebuilds from them.
Run this after merge_new_resources.py (or any edit to community_resources.json).

Classification is source-first (each fetcher's `source` string reliably names its registry/
country), with an address/description/website-TLD fallback for the long tail of individually
curated entries that don't come from a bulk registry fetch.

Big countries are split into sub-shards so a search downloads only its own part: France by région
(europe/FR-IDF.json, ...) and Japan by region (world/JP-KANTO.json, ...). Every world country with a
bulk registry gets its own world/<CC>.json; world/all.json holds only what has no country shard,
because the app loads it on EVERY search and it has to stay small.

Each manifest entry also lists the shard's `cells`: the 1°x1° grid squares its located entries fall
in. index.html uses them to fetch only the shards a search area touches, instead of every shard.

    python3 tools/split_by_region.py                   # re-split community_resources.json into data/
    python3 tools/split_by_region.py --manifest-only   # rewrite data/manifest.json from the shards on disk
"""
import json
import math
import os
import re
import shutil
import sys
from collections import Counter

IN_PATH = "community_resources.json"
DATA_DIR = "data"
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
    "cyprus","cypriot","malta","maltese","iceland","icelandic","luxembourg","russia","russian",
]
WORLD_COUNTRY_WORDS = [
    "australia","australian","new zealand","canada","canadian","brazil","brazilian","mexico",
    "mexican","argentina","argentine","colombia","colombian","japan","japanese","korea","korean",
    "israel","israeli","india","indian","singapore","south africa","china","chinese","taiwan",
]

EURO_TLDS = {"ru","ie","uk","fr","de","it","es","nl","be","pl","fi","se","no","dk","ch","at","pt",
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
    "russia federal resource centre", "russia ministry of", "russia ministry of justice",
    "russian society of the deaf",
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

# Explicit routing for the registry sources added from 2026-10-12 on: lowercase source substring ->
# (bucket, shard code). The code is the shard name; None means "derive it" (US state from the address).
# Checked BEFORE the broad pattern lists above, so an unrelated substring such as "card" cannot misroute them.
NEW_SOURCE_SHARDS = [
    ("brazil ipea", "world", "BR"),
    ("nces common core", "us", None),
    ("california department of developmental services", "us", None),
    ("ohio department of developmental disabilities certified providers", "us", None),
    ("new york opwdd provider agencies", "us", None),
    ("new york medicaid enrolled provider", "us", None),
    ("irs exempt organizations business master file (ntee disability", "us", None),
    ("england & wales charity commission register (disability", "europe", "GB"),
    ("autismo españa member and linked", "europe", "ES"),
    ("england gias", "europe", "GB"),
    ("denmark stil", "europe", "DK"),
    ("sweden skolverket", "europe", "SE"),
    ("france finess", "europe", "FR"),
    ("poland rspo", "europe", "PL"),
    ("finland ptv", "europe", "FI"),
    ("norway udir nsr", "europe", "NO"),
    ("norway bronnoysund", "europe", "NO"),
    ("japan wam net", "world", "JP"),
    ("sweden socialstyrelsen", "europe", "SE"),
    ("latvia ministry of welfare", "europe", "LV"),
    ("scotland oscr", "europe", "GB"),
    ("israel registrar of amutot", "world", "IL"),
    ("mexico sat directory", "world", "MX"),
    ("colombia rues", "world", "CO"),
    ("argentina igj", "world", "AR"),
    ("aragon register of associations", "europe", "ES"),
    ("castilla y leon patient associations", "europe", "ES"),
    ("dh danske handicaporganisationer", "europe", "DK"),
    ("lev (landsforeningen lev)", "europe", "DK"),
    ("autismeforeningen", "europe", "DK"),
    ("autismiliitto", "europe", "FI"),
    ("kuuloliitto", "europe", "FI"),
    ("näkövammaisten liitto", "europe", "FI"),
    ("moldova public services agency", "europe", "MD"),
    ("montenegro register of active ngos", "europe", "ME"),
    ("estonia e-business", "europe", "EE"),
    ("australia acnc", "world", "AU"),
    ("new zealand charities services", "world", "NZ"),
    ("canada revenue agency list of charities", "world", "CA"),
    ("russia voi", "europe", "RU"),
    ("scotland care inspectorate", "europe", "GB"),
    ("northern ireland rqia", "europe", "GB"),
    ("argentina padron", "world", "AR"),
    ("japan mext", "world", "JP"),
    ("wales care inspectorate wales", "europe", "GB"),
    ("wales welsh government address list", "europe", "GB"),
    ("austria statistik austria", "europe", "AT"),
    ("austria vienna open data", "europe", "AT"),
    ("austria upper austria", "europe", "AT"),
    ("austria burgenland", "europe", "AT"),
    ("austria tirol", "europe", "AT"),
    ("netherlands duo", "europe", "NL"),
    ("czech republic rpss", "europe", "CZ"),
    ("austria neba", "europe", "AT"),
    ("austria behindertenrat", "europe", "AT"),
    ("bosnia and herzegovina e-register", "europe", "BA"),
    ("bosnia and herzegovina fbih", "europe", "BA"),
    ("bosnia and herzegovina sarajevo canton", "europe", "BA"),
]

# France: 5-digit postcode -> département -> région, so the 40k+ French rows split into shards of a few MB.
FR_REGION_DEPTS = {
    "ARA": "01 03 07 15 26 38 42 43 63 69 73 74",
    "BFC": "21 25 39 58 70 71 89 90",
    "BRE": "22 29 35 56",
    "CVL": "18 28 36 37 41 45",
    "COR": "20",
    "GES": "08 10 51 52 54 55 57 67 68 88",
    "HDF": "02 59 60 62 80",
    "IDF": "75 77 78 91 92 93 94 95",
    "NOR": "14 27 50 61 76",
    "NAQ": "16 17 19 23 24 33 40 47 64 79 86 87",
    "OCC": "09 11 12 30 31 32 34 46 48 65 66 81 82",
    "PDL": "44 49 53 72 85",
    "PAC": "04 05 06 13 83 84",
}
FR_DEPT_REGION = {d: r for r, ds in FR_REGION_DEPTS.items() for d in ds.split()}
FR_POSTCODE_RE = re.compile(r"\b(\d{5})\b")


def fr_region_code(entry: dict) -> str:
    """'FR-<région>' from the postcode in the address ('FR-OM' for overseas); plain 'FR' when none parses."""
    for pc in FR_POSTCODE_RE.findall(entry.get("address") or ""):
        if pc[:2] in ("97", "98"):
            return "FR-OM"
        if pc[:2] in FR_DEPT_REGION:
            return "FR-" + FR_DEPT_REGION[pc[:2]]
    return "FR"


# Japan: addresses start with the prefecture name; eight classic regions keep every shard in single-digit MB.
JP_REGIONS = {
    "HOKKAIDO": "北海道",
    "TOHOKU": "青森県 岩手県 宮城県 秋田県 山形県 福島県",
    "KANTO": "茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県",
    "CHUBU": "新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県",
    "KINKI": "三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県",
    "CHUGOKU": "鳥取県 島根県 岡山県 広島県 山口県",
    "SHIKOKU": "徳島県 香川県 愛媛県 高知県",
    "KYUSHU": "福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県",
}
JP_PREF_REGION = {p: r for r, ps in JP_REGIONS.items() for p in ps.split()}


def jp_region_code(entry: dict) -> str:
    """'JP-<region>' from the prefecture at the start of the address; plain 'JP' when none parses."""
    addr = (entry.get("address") or "").replace("〒", " ")
    addr = re.sub(r"^[\s\d\-]+", "", addr)
    for pref, reg in JP_PREF_REGION.items():
        if addr.startswith(pref):
            return "JP-" + reg
    return "JP"


def forced_shard(source: str):
    """(bucket, code) for the sources in NEW_SOURCE_SHARDS, else None."""
    s = source.lower()
    for pat, bucket, code in NEW_SOURCE_SHARDS:
        if pat in s:
            return bucket, code
    return None


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


# ── Sub-region classification (US state / European country) ──────────────────────────────────
US_STATE_TAIL_RE = re.compile(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b")
US_STATE_COMMA_RE = re.compile(r",\s*([A-Z]{2})\s*(?:,|$)")
US_TERRITORIES = {"PR", "GU", "AS", "VI", "MP", "PW"}
US_VALID = US_STATE_ABBR | US_TERRITORIES

# Source-string substring -> ISO country code (checked in order, lowercase).
EURO_SOURCE_COUNTRY = [
    ("france rna", "FR"), ("cqc (uk", "GB"), ("england & wales charity", "GB"),
    ("northern ireland charity", "GB"), ("ukraine", "UA"), ("catalonia", "ES"), ("madrid", "ES"),
    ("canarias", "ES"), ("basque country", "ES"), ("italy runts", "IT"), ("netherlands anbi", "NL"),
    ("germany bzst", "DE"), ("belgium kbo", "BE"), ("norway bronnoysund", "NO"),
    ("czech republic ares", "CZ"), ("slovakia rpo", "SK"), ("estonia e-business", "EE"),
    ("latvia register", "LV"), ("finland prh", "FI"), ("greece gemi", "GR"),
    ("switzerland zefix", "CH"), ("slovenia ajpes", "SI"), ("cyprus register", "CY"),
    ("bulgaria commercial", "BG"), ("russia ", "RU"), ("russian society", "RU"),
]
# Name/word -> code for address and description matching.
EURO_COUNTRY_WORDS = {
    "united kingdom": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "ireland": "IE", "france": "FR", "germany": "DE", "deutschland": "DE",
    "italy": "IT", "italia": "IT", "spain": "ES", "españa": "ES", "netherlands": "NL",
    "belgium": "BE", "belgique": "BE", "poland": "PL", "polska": "PL", "finland": "FI",
    "sweden": "SE", "norway": "NO", "denmark": "DK", "switzerland": "CH", "austria": "AT",
    "portugal": "PT", "greece": "GR", "czech": "CZ", "slovakia": "SK", "slovenia": "SI",
    "estonia": "EE", "latvia": "LV", "lithuania": "LT", "ukraine": "UA", "hungary": "HU",
    "romania": "RO", "bulgaria": "BG", "croatia": "HR", "cyprus": "CY", "malta": "MT",
    "iceland": "IS", "luxembourg": "LU", "russia": "RU", "россия": "RU",
}
# Adjective forms only used on descriptions ("Irish nonprofit", ...).
EURO_ADJECTIVES = {
    "irish": "IE", "french": "FR", "german": "DE", "italian": "IT", "spanish": "ES", "dutch": "NL",
    "belgian": "BE", "polish": "PL", "finnish": "FI", "swedish": "SE", "norwegian": "NO",
    "danish": "DK", "swiss": "CH", "austrian": "AT", "portuguese": "PT", "greek": "GR",
    "slovak": "SK", "slovenian": "SI", "estonian": "EE", "latvian": "LV", "lithuanian": "LT",
    "ukrainian": "UA", "hungarian": "HU", "romanian": "RO", "bulgarian": "BG", "croatian": "HR",
    "cypriot": "CY", "maltese": "MT", "icelandic": "IS", "russian": "RU", "british": "GB", "scottish": "GB",
    "welsh": "GB", "english": "GB",
}
EURO_TLD_COUNTRY = {
    "ie": "IE", "uk": "GB", "fr": "FR", "de": "DE", "it": "IT", "es": "ES", "nl": "NL", "be": "BE",
    "pl": "PL", "fi": "FI", "se": "SE", "no": "NO", "dk": "DK", "ch": "CH", "at": "AT", "pt": "PT",
    "gr": "GR", "cz": "CZ", "sk": "SK", "si": "SI", "ee": "EE", "lv": "LV", "lt": "LT", "ua": "UA",
    "ru": "RU", "hu": "HU", "ro": "RO", "bg": "BG", "hr": "HR", "cy": "CY", "mt": "MT", "is": "IS", "lu": "LU",
}


def us_state(entry: dict) -> str:
    """Two-letter state/territory code, or 'national' when the address names none."""
    addr = entry.get("address") or ""
    m = US_STATE_TAIL_RE.findall(addr)
    for code in reversed(m):
        if code in US_VALID:
            return code
    for code in reversed(US_STATE_COMMA_RE.findall(addr)):
        if code in US_VALID:
            return code
    return "national"


# The curated UK organisations at the tail of EUROPE_SOURCE_PATTERNS (from "national autistic
# society" on) are all UK-based even when the entry carries no address.
UK_SOURCE_PATTERNS = EUROPE_SOURCE_PATTERNS[EUROPE_SOURCE_PATTERNS.index("national autistic society"):]


def europe_country(entry: dict) -> str:
    """ISO country code for a European entry, or 'other' when nothing identifies one."""
    s = (entry.get("source") or "").lower()
    for pat, code in EURO_SOURCE_COUNTRY:
        if pat in s:
            return code
    if any(p in s for p in UK_SOURCE_PATTERNS):
        return "GB"
    addr = (entry.get("address") or "")
    low = addr.lower()
    for w, code in EURO_COUNTRY_WORDS.items():
        if re.search(rf"\b{re.escape(w)}\b", low):
            return code
    if UK_POSTCODE_RE.search(addr):
        return "GB"
    site = (entry.get("website") or "").lower().split("//")[-1].split("/")[0]
    tld = site.rsplit(".", 1)[-1] if "." in site else ""
    if tld in EURO_TLD_COUNTRY:
        return EURO_TLD_COUNTRY[tld]
    desc = (entry.get("description") or "").lower()
    for w, code in {**EURO_COUNTRY_WORDS, **EURO_ADJECTIVES}.items():
        if re.search(rf"\b{re.escape(w)}\b", desc):
            return code
    return "other"


def write_shard(path: str, entries: list):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n" + ",\n".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in entries) + "\n]\n")


def located(entry: dict):
    """(lat, lng) for an entry the app puts on the map, else None (placeless or no coordinates)."""
    c = entry.get("coordinates") or {}
    lat, lng = c.get("lat"), c.get("lng")
    if entry.get("placeless") or not lat or not lng:
        return None
    return lat, lng


def shard_cells(entries: list) -> list:
    """Sorted 1°x1° grid cells holding the shard's located entries, each encoded as
    (floor(lat) + 90) * 360 + (floor(lng) + 180) % 360 -- the same formula as cellKey() in index.html.
    Cells rather than one bounding box: France's overseas territories alone would stretch its box
    over most of the globe, so every US search would download France."""
    cells = set()
    for e in entries:
        p = located(e)
        if p:
            cells.add((math.floor(p[0]) + 90) * 360 + (math.floor(p[1]) + 180) % 360)
    return sorted(cells)


def manifest_entry(rel: str, region: str, code: str, entries: list) -> dict:
    return {"file": rel, "region": region, "code": code, "count": len(entries), "cells": shard_cells(entries)}


def write_manifest(total: int, files: list):
    # One line per shard: the cell lists would otherwise put thousands of lines in the diff.
    with open(os.path.join(DATA_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        f.write('{"total": %d, "files": [\n' % total)
        f.write(",\n".join(json.dumps(m, separators=(",", ":")) for m in files))
        f.write("\n]}\n")


def report_wide_shards(shards: dict):
    """Print shards whose located entries span an unusually wide area -- usually a few entries with
    wrong coordinates (or real overseas territories) worth a look. Cells keep the app correct either way."""
    wide = []
    for rel, entries in shards.items():
        pts = [p for p in map(located, entries) if p]
        if not pts:
            continue
        lats, lngs = [p[0] for p in pts], [p[1] for p in pts]
        if max(lats) - min(lats) > 20 or max(lngs) - min(lngs) > 40:
            wide.append((rel, min(lats), min(lngs), max(lats), max(lngs)))
    if wide:
        print("Shards spanning an unusually wide area (lat > 20° or lng > 40°) -- check for stray coordinates:")
        for rel, a, b, c, d in wide:
            print(f"  {rel:<22} lat {a:7.2f} .. {c:7.2f}   lng {b:8.2f} .. {d:8.2f}")


def rebuild_manifest_only():
    """Rewrite data/manifest.json from the shard files already on disk -- same files, same order --
    without rewriting any shard (main() always regenerates every shard)."""
    with open(os.path.join(DATA_DIR, "manifest.json"), encoding="utf-8") as f:
        old = json.load(f)
    files, shards, total = [], {}, 0
    for m in old["files"]:
        with open(os.path.join(DATA_DIR, m["file"]), encoding="utf-8") as f:
            entries = json.load(f)
        files.append(manifest_entry(m["file"], m["region"], m["code"], entries))
        shards[m["file"]] = entries
        total += len(entries)
    if total != old.get("total"):
        print(f"Note: shards hold {total} entries; the old manifest said {old.get('total')}.")
    write_manifest(total, files)
    print(f"Rewrote {DATA_DIR}/manifest.json: {len(files)} shards, {total} entries, "
          f"{sum(len(m['cells']) for m in files)} grid cells.")
    report_wide_shards(shards)


def main():
    with open(IN_PATH, encoding="utf-8") as f:
        data = json.load(f)

    buckets = {"us": [], "europe": [], "world": []}
    forced_code = {}   # id(entry) -> shard code, for entries routed by NEW_SOURCE_SHARDS
    source_bucket_counts = Counter()
    unclassified = []

    for entry in data:
        source = (entry.get("source") or "").strip()
        name = entry.get("name")
        bucket = None
        method = None
        rule = forced_shard(source)
        if rule:
            bucket, method = rule[0], "rule"
            if rule[1]:
                forced_code[id(entry)] = rule[1]
        if bucket is None and name in MANUAL_OVERRIDES:
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

    shards = {}  # (region, code) -> entries, canonical order preserved
    for e in buckets["us"]:
        shards.setdefault(("us", us_state(e)), []).append(e)
    for e in buckets["europe"]:
        addr = e.get("address") or ""
        code = forced_code.get(id(e))
        if code is None:
            # A few US/Canadian orgs were bucketed Europe by their source string; route them home.
            if any(c in US_VALID for c in US_STATE_TAIL_RE.findall(addr)):
                shards.setdefault(("us", us_state(e)), []).append(e)
                continue
            if CA_POSTAL_RE.search(addr):
                shards[("world", "all")] = shards.get(("world", "all"), []) + [e]
                continue
            code = europe_country(e)
        if code == "FR":
            code = fr_region_code(e)
        shards.setdefault(("europe", code), []).append(e)
    world_all = []
    for e in buckets["world"]:
        code = forced_code.get(id(e))
        if code == "JP":
            code = jp_region_code(e)
        if code:
            shards.setdefault(("world", code), []).append(e)
        else:
            world_all.append(e)
    shards[("world", "all")] = world_all + shards.get(("world", "all"), [])

    # Regenerate the shard folder from scratch so a state/country that empties out disappears.
    if os.path.isdir(DATA_DIR):
        shutil.rmtree(DATA_DIR)
    order = {"us": 0, "europe": 1, "world": 2}
    manifest = []
    for (region, code), entries in sorted(shards.items(), key=lambda kv: (order[kv[0][0]], kv[0][1])):
        rel = f"{region}/{code}.json"
        write_shard(os.path.join(DATA_DIR, rel), entries)
        manifest.append(manifest_entry(rel, region, code, entries))
    write_manifest(len(data), manifest)

    print(f"Total entries: {len(data)}")
    print(f"  US:     {len(buckets['us']):>7}")
    print(f"  Europe: {len(buckets['europe']):>7}")
    print(f"  World:  {len(buckets['world']):>7}")
    print(f"  Sum:    {sum(len(v) for v in buckets.values()):>7}")
    print(f"Unclassified (defaulted to World): {len(unclassified)}")
    print(f"Shards written: {len(manifest)} files under {DATA_DIR}/ "
          f"(largest {max(m['count'] for m in manifest)} entries)")
    print(f"  US 'national' (no state in address): {len(shards.get(('us', 'national'), []))}")
    print(f"  Europe 'other' (no country found):   {len(shards.get(('europe', 'other'), []))}")
    report_wide_shards({f"{region}/{code}.json": entries for (region, code), entries in shards.items()})

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
    if "--manifest-only" in sys.argv[1:]:
        rebuild_manifest_only()
    else:
        main()
