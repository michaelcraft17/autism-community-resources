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
     wixsite.com, ...) that many unrelated small orgs use as their only site,
     AND UNLESS the entry carries its own external_id. Registry rows with an ID
     (schools listing their municipality's site, establishments sharing an
     operator's site, federation branch pages, ...) legitimately share domains;
     the ID is authoritative for them. The number of entries the domain rule
     WOULD have dropped is still measured and printed per file, so the effect of
     skipping it is visible before anything is merged (2026-10-12).
  3. (norm_name, norm_city) -- NOT name alone. Measured on Brazil's Mapa OSC
     data: name-only matching would have silently dropped 665 real disability
     orgs and 46 real autism orgs, because entire federated networks (APAE:
     261 branches, one per city; AMA: 8 branches) share one legal name across
     different cities. norm_name also applies script-specific normalization
     (Japanese legal-form affixes, Hebrew registration suffixes, PT/ES accents
     and legal-form words) so the same org matches across sources without
     over-collapsing distinct ones.

Usage:
    python3 tools/merge_new_resources.py                       # every new_resources_*.json in the repo root
    python3 tools/merge_new_resources.py new_resources_japan.json [...]   # only the named files

Naming files matters: the old, already-merged new_resources_*.json files are
gitignored scratch that stays on disk, and re-running them can resurrect rows
that were deliberately removed from community_resources.json by hand.

The app derives a listing's id from hash(name|address|source), and shows one
listing per id. Entries whose (name, address, source) triple already exists, or
repeats inside the file, would be invisible in the app, so they are skipped and
reported as "id collision" -- the build scripts should merge such rows (e.g. one
entry per site with all its services) instead.

After running, rewrite the data/ shards the app loads:
    python3 tools/split_by_region.py
"""
import sys
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
    # "..., City, State[, ZIP]" -- if the last segment is a postal code
    # (mostly digits), the city is 3rd-from-end, not 2nd (which would be the
    # state/UF and would wrongly conflate different cities in the same state).
    if len(parts) >= 3 and re.match(r"^\d{4,9}[\-\d]*$", parts[-1]):
        city = parts[-3]
    else:
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
    # key -> sources already holding that (name, city); lets a registry's own rows (same source, own
    # external_id) coexist when a name repeats within one city.
    seen_name_city = {}
    for r in main_data:
        seen_name_city.setdefault((norm_name(r.get("name")), norm_city(r.get("address"))), set()).add(
            (r.get("source"), bool(r.get("external_id"))))
    seen_domains = {norm_domain(r.get("website")) for r in main_data if r.get("website")}
    seen_domains.discard(None)
    seen_ids = {
        (r.get("name") or "", r.get("address") or "", r.get("source") or "")
        for r in main_data if not r.get("npi_number")
    }

    if len(sys.argv) > 1:
        files = [a if os.path.isabs(a) else os.path.join(REPO, a) for a in sys.argv[1:]]
    else:
        files = sorted(glob.glob(os.path.join(REPO, "new_resources_*.json")))
    added_total = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
        added = 0
        skipped = 0
        skip_log = []
        domain_would_drop = 0   # entries the domain rule would have dropped but the external_id exemption kept
        skipped_by = {}
        for e in entries:
            eid = e.get("external_id")
            src = e.get("source")
            n = norm_name(e.get("name"))
            city = norm_city(e.get("address"))
            d = norm_domain(e.get("website"))

            is_dup = False
            matched_on = None
            ident = (e.get("name") or "", e.get("address") or "", e.get("source") or "")
            if eid and (src, eid) in seen_external_ids:
                is_dup, matched_on = True, "external_id"
            elif d and d not in SHARED_PLATFORM_DOMAINS and d in seen_domains:
                if eid:
                    domain_would_drop += 1   # exempt: the registry ID is authoritative
                else:
                    is_dup, matched_on = True, "domain"
            if not is_dup:
                holders = seen_name_city.get((n, city))
                if holders and not (eid and all(s_ == src and had_id for s_, had_id in holders)):
                    is_dup, matched_on = True, "name+city"
            if not is_dup and not e.get("npi_number") and ident in seen_ids:
                is_dup, matched_on = True, "id collision"

            if is_dup:
                skipped += 1
                skipped_by[matched_on] = skipped_by.get(matched_on, 0) + 1
                flag = ""
                if matched_on == "name+city" and (len(n) < 6 or not city):
                    flag = "  [REVIEW: short/placeless key]"
                skip_log.append(f"  SKIP ({matched_on}){flag}: {e.get('name')!r} @ {e.get('address')!r}")
                continue

            main_data.append(e)
            if eid:
                seen_external_ids.add((src, eid))
            seen_name_city.setdefault((n, city), set()).add((src, bool(eid)))
            if not e.get("npi_number"):
                seen_ids.add(ident)
            if d:
                seen_domains.add(d)
            added += 1

        assert added + skipped == len(entries), (
            f"{path}: added({added}) + skipped({skipped}) != input({len(entries)})"
        )
        added_total += added
        print(f"{os.path.basename(path)}: {added} added, {skipped} skipped as duplicates"
              + (f" {skipped_by}" if skipped_by else ""))
        if domain_would_drop:
            print(f"    (domain rule would also have dropped {domain_would_drop} entries that carry an external_id; kept)")
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
