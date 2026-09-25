#!/usr/bin/env python3
"""
Merge every tools/../new_resources_*.json file in the repo root into
community_resources.json, deduping against the existing dataset and across the
new files themselves.

Dedup key precedence (fixed 2026-09-25 -- see HANDOFF.md "dedup bug"):
  1. (source, external_id) when the entry carries a registry's own stable ID
     (CNPJ, RFC, amutot number, Japanese houjin-bangou, ABN, BN, EIN, NZ
     charity number, Florida doc number, IGJ numero_correlativo, ...).
  2. website domain, UNLESS the domain is a shared platform (facebook.com,
     wixsite.com, ...) that many unrelated small orgs use as their only site.
  3. (norm_name, norm_city) -- NOT name alone. Measured on Brazil's Mapa OSC
     data: name-only matching would have silently dropped 665 real disability
     orgs and 46 real autism orgs, because entire federated networks (APAE:
     261 branches, one per city; AMA: 8 branches) share one legal name across
     different cities. norm_name also applies script-specific normalization
     (Japanese legal-form affixes, Hebrew registration suffixes, PT/ES accents
     and legal-form words) so the same org matches across sources without
     over-collapsing distinct ones.

After running, regenerate community_data.js:
    node gen_community_data.js
"""
import glob
import json
import os
import re
import unicodedata

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PATH = os.path.join(REPO, "community_resources.json")

SHARED_PLATFORM_DOMAINS = {
    "facebook.com", "wixsite.com", "blogspot.com", "sites.google.com",
    "linktr.ee", "instagram.com", "wordpress.com", "weebly.com",
}

JAPANESE_LEGAL_AFFIXES = [
    "特定非営利活動法人", "一般社団法人", "一般財団法人", "公益社団法人",
    "公益財団法人", "社会福祉法人", "npo法人", "株式会社",
]

PT_ES_LEGAL_WORDS = [
    "associacao", "asociacion", "fundacao", "fundacion", "instituto",
    "ac", "a c", "iap", "sin fines de lucro", "sem fins lucrativos",
]


def _strip_diacritics(s):
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def norm_name(name):
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name).lower()

    # Hebrew registration suffixes: (ע"ר) appears as (ע~ר) in some exports
    # (~ standing in for quote marks), also בע~מ, חל~צ. Strip stray letters
    # and niqqud (Hebrew combining marks) so these don't create false
    # *mismatches* (the opposite failure mode from the collapse bug).
    s = re.sub(r"\(?\s*ע[~\"']?ר\s*\)?", "", s)
    s = re.sub(r"\(?\s*בע[~\"']?מ\s*\)?", "", s)
    s = re.sub(r"\(?\s*חל[~\"']?צ\s*\)?", "", s)
    s = "".join(c for c in s if not unicodedata.category(c) == "Mn")  # niqqud

    for affix in JAPANESE_LEGAL_AFFIXES:
        s = s.replace(affix, "")

    # PT/ES: strip accents, then legal-form words as whole tokens.
    ascii_ish = _strip_diacritics(s)
    if ascii_ish != s and any(ch.isalpha() and ord(ch) < 0x2000 for ch in s):
        s = ascii_ish
    tokens = [t for t in re.split(r"\s+", s) if t]
    tokens = [t for t in tokens if t.strip(".,") not in PT_ES_LEGAL_WORDS]
    s = " ".join(tokens)

    # Unicode-aware: str.isalnum() recognizes non-Latin letters (Cyrillic,
    # Greek, CJK, Hebrew, ...) too, unlike an ASCII-only [^a-z0-9] regex,
    # which silently collapsed every non-Latin-script name to an empty or
    # near-empty key -- confirmed to have dropped real, distinct
    # organizations as false "duplicates" for both Ukraine (Cyrillic) and
    # Cyprus (Greek) entries before this fix.
    return "".join(c for c in s if c.isalnum())


def norm_city(address):
    """Heuristic city extraction from a free-text address string.

    Addresses in this dataset are wildly heterogeneous across ~40 countries'
    sources, so this is deliberately a coarse fallback signal for the dedup
    key, not a real address parser: take the second-to-last comma-separated
    segment (the common "..., City, State/Country ZIP" or "..., City, State"
    shape), strip digits/punctuation, normalize case and accents.
    """
    if not address:
        return ""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) < 2:
        return norm_name(address)  # single-segment address, best effort
    city = parts[-2]
    city = re.sub(r"\d+", "", city)
    return norm_name(city)


def norm_domain(url):
    if not url:
        return None
    m = re.search(r"^(?:https?://)?(?:www\.)?([^/]+)", url.strip())
    return m.group(1).lower() if m else None


def main():
    with open(MAIN_PATH, encoding="utf-8") as f:
        main_data = json.load(f)
    print(f"Existing entries: {len(main_data)}")

    seen_external_ids = {
        (r.get("source"), r.get("external_id"))
        for r in main_data
        if r.get("external_id")
    }
    seen_name_city = {(norm_name(r.get("name")), norm_city(r.get("address"))) for r in main_data}
    seen_domains = {norm_domain(r.get("website")) for r in main_data if r.get("website")}
    seen_domains.discard(None)

    files = sorted(glob.glob(os.path.join(REPO, "new_resources_*.json")))
    added_total = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
        added = 0
        skipped = 0
        skip_log = []
        for e in entries:
            eid = e.get("external_id")
            src = e.get("source")
            n = norm_name(e.get("name"))
            city = norm_city(e.get("address"))
            d = norm_domain(e.get("website"))

            is_dup = False
            matched_on = None
            if eid and (src, eid) in seen_external_ids:
                is_dup, matched_on = True, "external_id"
            elif d and d not in SHARED_PLATFORM_DOMAINS and d in seen_domains:
                is_dup, matched_on = True, "domain"
            elif (n, city) in seen_name_city:
                is_dup, matched_on = True, "name+city"

            if is_dup:
                skipped += 1
                flag = ""
                if matched_on == "name+city" and (len(n) < 6 or not city):
                    flag = "  [REVIEW: short/placeless key]"
                skip_log.append(f"  SKIP ({matched_on}){flag}: {e.get('name')!r} @ {e.get('address')!r}")
                continue

            main_data.append(e)
            if eid:
                seen_external_ids.add((src, eid))
            seen_name_city.add((n, city))
            if d:
                seen_domains.add(d)
            added += 1

        assert added + skipped == len(entries), (
            f"{path}: added({added}) + skipped({skipped}) != input({len(entries)})"
        )
        added_total += added
        print(f"{os.path.basename(path)}: {added} added, {skipped} skipped as duplicates")
        if skip_log:
            log_path = os.path.join(REPO, "tools", "logs", "merge_skips.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"\n=== {os.path.basename(path)} ===\n")
                lf.write("\n".join(skip_log) + "\n")

    with open(MAIN_PATH, "w", encoding="utf-8") as f:
        json.dump(main_data, f, ensure_ascii=False)

    print(f"\nTotal added: {added_total}")
    print(f"New total entries: {len(main_data)}")


if __name__ == "__main__":
    main()
