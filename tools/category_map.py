"""
Shared category-mapping helper (round-4 research, section 1).

Precedence: name/purpose keyword override first (most specific signal) ->
source's own registry code -> general_support as last resort. This replaces
blind-defaulting new sources to general_support and reduces the qwen
classifier pass to genuine leftovers only.

Usage:
    from category_map import classify
    entry_type = classify(name, purpose_text, code_table_lookup=some_dict.get(code))
"""
import re

KEYWORDS = [
    ("education", [
        "school", "escola", "escuela", "colegio", "école", "schule", "학교",
        "学校", "בית ספר", "ensino", "educaç", "educac", "kindergarten",
        "jardín", "creche", "instituto educativo",
    ]),
    ("therapy", [
        "therap", "terapi", "terapia", "aba", "fono", "fonoaudiolog",
        "speech", "logoped", "fisioterap", "occupational", "ergoterap",
        "rehabilit", "reabilit", "reabilitação", "habilitación",
        "estimulación", "療育", "שיקום",
    ]),
    ("medical", [
        "hospital", "clínic", "clinic", "klinik", "médic", "medical",
        "psychiatr", "neurolog", "diagnós", "diagnost", "salud mental",
        "saúde mental",
    ]),
    ("advocacy", [
        "rights", "direitos", "derechos", "drets", "rechte", "advocacy",
        "defesa", "defensa", "federación", "federação", "federation",
        "confederación", "council", "rede", "red de", "network",
    ]),
    ("social", [
        "sport", "esporte", "deporte", "club", "clube", "recreation",
        "recreação", "camp", "campamento", "lazer", "ocio", "art", "arte",
        "music", "música", "theatre", "teatro",
    ]),
]

VALID_TYPES = {"advocacy", "therapy", "education", "medical", "social", "general_support"}


def keyword_override(*texts):
    blob = " ".join(t.lower() for t in texts if t)
    for type_, words in KEYWORDS:
        for w in words:
            if w in blob:
                return type_
    return None


def classify(name=None, purpose=None, code_type=None):
    """code_type: the source-specific code table's lookup result, if any
    (e.g. Brazil CNAE -> type, per round-4 section 1a-1i tables), already
    resolved by the caller. Falls back to general_support."""
    kw = keyword_override(name or "", purpose or "")
    if kw:
        return kw
    if code_type in VALID_TYPES:
        return code_type
    return "general_support"


# Per-source code tables (round 4, sections 1a-1i), for callers to use
# directly with dict.get(code, "general_support") before calling classify().

BRAZIL_CNAE = {
    "94308": "advocacy", "88006": "general_support", "94995": "general_support",
    "87301": "general_support", "87115": "general_support", "85139": "education",
    "87204": "therapy", "94936": "social", "93191": "social", "86305": "medical",
    "86909": "therapy", "93123": "social", "94120": "advocacy", "85996": "education",
    "86500": "therapy", "94910": "general_support",
}


def brazil_cnae_type(cnae):
    if not cnae:
        return "general_support"
    cnae = str(cnae)
    if cnae in BRAZIL_CNAE:
        return BRAZIL_CNAE[cnae]
    prefix3 = cnae[:3]
    if prefix3 in ("851", "852", "853", "854", "855", "856", "857", "858", "859"):
        return "education"
    if prefix3 in ("861", "863"):
        return "medical"
    if prefix3 == "865":
        return "therapy"
    if cnae[:2] == "88":
        return "general_support"
    return "general_support"
