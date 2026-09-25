"""
Audit the 521 entries carrying a vague legacy `source` value that predates
this project's "official registry only" discipline ("National Resources 2026",
"State Resources 2025 - <State>", "California Resources 2025", "university",
etc.) -- see HANDOFF.md for the full list and why they're suspect.

Classifies each into one of three buckets, using real verification only
(no LLM narration, no guessing -- same discipline as everything else in this
project):
  - VERIFIED: the entry's own website is reachable, isn't a parking/aggregator
    page, and its content genuinely matches the org (reuses the aggregator
    blocklist + name-token-match logic from find_websites_by_address.py), OR
    a real web search independently confirms the org exists.
  - CLEARLY_BAD: the existing website (if any) is dead/parked/unrelated AND an
    independent real search for the org's name returns zero results anywhere
    -- the high bar is deliberate (bias against removal: a false removal of a
    real org is worse than leaving one sitting as unverified).
  - UNVERIFIED: everything else (no website + no search evidence either way,
    or a website that fails verification but a search still finds *something*
    inconclusive). Left in the dataset untouched.

Only CLEARLY_BAD is a removal candidate, and even then this script only
LOGS them -- actually deleting from community_resources.json is a separate,
deliberate step after reviewing the log.

Usage:
    python3 tools/audit_legacy_sources.py
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
import urllib.request

from ddgs import DDGS

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "community_resources.json"
LOG_DIR = ROOT / "tools" / "logs"

VAGUE_PREFIXES = [
    "National Resources", "Nationwide Services", "State Resources",
    "San Jose Expansion", "California Resources", "university",
]

PARKING_SIGNALS = [
    "domain is for sale", "buy this domain", "this domain may be for sale",
    "domain name is parked", "domain has expired", "renew your domain",
    "this web page is parked", "domain parking", "future home of something quite cool",
    "the sponsored listings displayed above are served",
]

STOPWORDS = {"the", "of", "for", "and", "inc", "llc", "foundation", "center", "centre",
             "association", "society", "autism", "a", "an", "national", "office"}

AGGREGATOR_DOMAINS = {
    "medicarelist.com", "ehealthscores.com", "npino.com", "findabatherapy.org",
    "findabaproviders.com", "bizapedia.com", "nonprofitlist.org", "govserv.org",
    "psychologytoday.com", "npidb.org", "npiprofile.com", "healthgrades.com",
    "wellness.com", "zocdoc.com", "mapquest.com", "manta.com", "chamberofcommerce.com",
    "local.com", "superpages.com", "dnb.com", "opencorporates.com",
    "yelp.com", "yellowpages.com", "opennpi.com", "opengovus.com", "findglocal.com",
    "findaba.net", "findhealthclinics.org", "providerspark.com", "spectrumheart.com",
    "abacarenetwork.com", "abahub.org", "mentalhealthus.org", "autismlifeandliving.org",
    "raisingbrilliance.org", "inclusiveprogramsguide.com", "volunteersanantonio.org",
    "atlantaparent.com", "alabamafamilycentral.org", "linkedin.com", "facebook.com",
    "guidestar.org", "candid.org", "greatnonprofits.org", "charitynavigator.org",
    "instagram.com", "twitter.com", "x.com",
}


def is_vague(source):
    if not isinstance(source, str):
        return False
    return any(source == p or source.startswith(p) for p in VAGUE_PREFIXES)


def is_aggregator(netloc):
    host = netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return any(host == d or host.endswith("." + d) for d in AGGREGATOR_DOMAINS)


def distinctive_tokens(name):
    tokens = re.findall(r"[A-Za-z0-9']+", name.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 2]


def fetch_page(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ResourceAudit/1.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final_url = resp.geturl()
        raw = resp.read(200_000)
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            text = raw.decode("latin-1", errors="ignore")
        return final_url, text


def check_existing_website(url, org_name):
    """Returns (verdict, detail) where verdict in {'ok','aggregator','dead','no_match'}."""
    try:
        parsed = urlparse(url)
        if not parsed.scheme:
            url = "https://" + url
    except Exception:
        pass
    try:
        final_url, html = fetch_page(url)
    except Exception as e:
        return "dead", f"unreachable: {e}"

    parsed = urlparse(final_url)
    if is_aggregator(parsed.netloc):
        return "aggregator", f"resolves to known aggregator/directory: {parsed.netloc}"
    if any(bad in parsed.netloc.lower() for bad in ["sedoparking.com", "godaddy.com/domain", "afternic.com", "dan.com"]):
        return "dead", f"redirected to parking host: {parsed.netloc}"

    lower_html = html.lower()
    for signal in PARKING_SIGNALS:
        if signal in lower_html:
            return "dead", f"parking-page content signal: {signal!r}"

    tokens = distinctive_tokens(org_name)
    if not tokens:
        return "no_match", "no distinctive name tokens to check"
    hits = sum(1 for t in tokens if t in lower_html)
    if hits == 0:
        return "no_match", f"none of the org's name tokens {tokens} found on the page"

    return "ok", final_url


def independent_search_evidence(name, address):
    """Real search for the org. Returns (found_any_result: bool, verified: bool, detail)."""
    city = ""
    if address:
        parts = [p.strip() for p in address.split(",")]
        if len(parts) >= 2:
            city = parts[-2] if not parts[-1].replace(" ", "").isdigit() else (parts[-3] if len(parts) >= 3 else parts[-2])
    query = f"{name} {city}".strip() if city else name
    try:
        results = list(DDGS().text(query, max_results=5))
    except Exception as e:
        return None, False, f"search error: {e}"

    if not results:
        return False, False, "zero search results"

    tokens = distinctive_tokens(name)
    for r in results:
        url = r.get("href") or r.get("url")
        if not url or not url.startswith("http"):
            continue
        if is_aggregator(urlparse(url).netloc):
            continue
        try:
            final_url, html = fetch_page(url)
        except Exception:
            continue
        if is_aggregator(urlparse(final_url).netloc):
            continue
        lower_html = html.lower()
        if any(sig in lower_html for sig in PARKING_SIGNALS):
            continue
        if tokens and sum(1 for t in tokens if t in lower_html) > 0:
            return True, True, f"independently verified via search: {final_url}"

    # results exist but none independently verified as the org's own site --
    # still real evidence something with this name shows up (snippets), just
    # not strong enough to call VERIFIED on its own.
    return True, False, f"{len(results)} search results found, none independently confirmed"


def audit_one(entry):
    name = entry.get("name", "")
    address = entry.get("address", "")
    website = entry.get("website")

    if website:
        verdict, detail = check_existing_website(website, name)
        if verdict == "ok":
            return {"name": name, "bucket": "VERIFIED", "evidence": f"own website reachable and matches: {detail}"}
        # website exists but failed direct check -- fall back to independent search
        found_any, verified, sdetail = independent_search_evidence(name, address)
        if verified:
            return {"name": name, "bucket": "VERIFIED", "evidence": f"website check failed ({verdict}: {detail}); {sdetail}"}
        if verdict == "dead" and found_any is False:
            return {"name": name, "bucket": "CLEARLY_BAD", "evidence": f"website dead ({detail}) AND zero independent search results for the org name"}
        return {"name": name, "bucket": "UNVERIFIED", "evidence": f"website check: {verdict} ({detail}); search: {sdetail}"}
    else:
        found_any, verified, sdetail = independent_search_evidence(name, address)
        if verified:
            return {"name": name, "bucket": "VERIFIED", "evidence": f"no website on file; {sdetail}"}
        if found_any is False:
            return {"name": name, "bucket": "CLEARLY_BAD", "evidence": "no website on file AND zero independent search results for the org name"}
        return {"name": name, "bucket": "UNVERIFIED", "evidence": f"no website on file; search: {sdetail}"}


def main():
    LOG_DIR.mkdir(exist_ok=True)
    data = json.load(open(DATA_FILE, encoding="utf-8"))
    targets = [d for d in data if is_vague(d.get("source"))]
    print(f"{len(targets)} vague-source entries to audit (of {len(data)} total)")

    with_site = [d for d in targets if d.get("website")]
    without_site = [d for d in targets if not d.get("website")]
    print(f"  {len(with_site)} have a website on file, {len(without_site)} do not")

    results = []

    # Phase 1: direct website checks, concurrent (different hosts, safe to parallelize).
    print("\nPhase 1: checking existing website fields directly...")
    to_recheck = []  # entries whose direct check failed and need a search fallback
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(check_existing_website, d["website"], d.get("name", "")): d for d in with_site}
        done = 0
        for fut in as_completed(futs):
            d = futs[fut]
            done += 1
            try:
                verdict, detail = fut.result()
            except Exception as e:
                verdict, detail = "dead", f"exception: {e}"
            if verdict == "ok":
                results.append({"name": d.get("name"), "address": d.get("address"), "source": d.get("source"),
                                 "bucket": "VERIFIED", "evidence": f"own website reachable and matches: {detail}"})
            else:
                to_recheck.append((d, verdict, detail))
            if done % 50 == 0:
                print(f"  ...{done}/{len(with_site)} direct checks done")
    print(f"Phase 1 done: {len(results)} VERIFIED directly, {len(to_recheck)} need a search fallback")

    # Phase 2: entries with no website at all, or whose direct check failed --
    # sequential + polite (shared search backend), one request at a time.
    fallback_list = list(without_site) + [d for d, _, _ in to_recheck]
    fail_detail = {id(d): (v, det) for d, v, det in to_recheck}
    print(f"\nPhase 2: independent search fallback for {len(fallback_list)} entries (sequential, polite)...")
    for n, d in enumerate(fallback_list, 1):
        name = d.get("name", "")
        address = d.get("address", "")
        found_any, verified, sdetail = independent_search_evidence(name, address)
        if verified:
            bucket = "VERIFIED"
            if id(d) in fail_detail:
                v, det = fail_detail[id(d)]
                evidence = f"website check failed ({v}: {det}); {sdetail}"
            else:
                evidence = f"no website on file; {sdetail}"
        elif found_any is False:
            bucket = "CLEARLY_BAD"
            if id(d) in fail_detail:
                v, det = fail_detail[id(d)]
                evidence = f"website dead ({det}) AND zero independent search results for the org name"
            else:
                evidence = "no website on file AND zero independent search results for the org name"
        else:
            bucket = "UNVERIFIED"
            if id(d) in fail_detail:
                v, det = fail_detail[id(d)]
                evidence = f"website check: {v} ({det}); search: {sdetail}"
            else:
                evidence = f"no website on file; search: {sdetail}"
        results.append({"name": name, "address": address, "source": d.get("source"), "bucket": bucket, "evidence": evidence})
        if n % 25 == 0:
            print(f"  ...{n}/{len(fallback_list)} fallback checks done")
        time.sleep(0.5)

    verified = [r for r in results if r["bucket"] == "VERIFIED"]
    bad = [r for r in results if r["bucket"] == "CLEARLY_BAD"]
    unverified = [r for r in results if r["bucket"] == "UNVERIFIED"]

    print(f"\n=== RESULTS ===")
    print(f"VERIFIED:     {len(verified)}")
    print(f"UNVERIFIED:   {len(unverified)}")
    print(f"CLEARLY_BAD:  {len(bad)}")
    print(f"Total:        {len(results)} (expected {len(targets)})")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = LOG_DIR / f"audit_legacy_sources_{ts}.json"
    json.dump({"verified": verified, "unverified": unverified, "clearly_bad": bad}, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nFull results: {out_path}")

    log_path = LOG_DIR / f"audit_legacy_sources_{ts}.log"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Legacy-source audit: {ts}\n")
        f.write(f"Total audited: {len(results)}\n")
        f.write(f"VERIFIED: {len(verified)}, UNVERIFIED: {len(unverified)}, CLEARLY_BAD: {len(bad)}\n\n")
        f.write("=== CLEARLY_BAD (removal candidates) ===\n")
        for r in bad:
            f.write(f"  {r['name']!r} | {r.get('address')!r} | {r.get('source')} | {r['evidence']}\n")
        f.write("\n=== UNVERIFIED (left in dataset) ===\n")
        for r in unverified:
            f.write(f"  {r['name']!r} | {r.get('address')!r} | {r.get('source')} | {r['evidence']}\n")
    print(f"Readable log: {log_path}")


if __name__ == "__main__":
    main()
