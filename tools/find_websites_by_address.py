"""
Find and verify official websites for entries currently missing one, using a
deterministic search query (name + city + country) run through a real search
engine (DuckDuckGo via the `ddgs` package) -- NOT an LLM guess. This project has
documented evidence (see HANDOFF.md) that letting a model output a URL directly
produces a ~50%+ fabrication rate; a real search plus real HTTP verification is
the only trustworthy path.

Every candidate URL must pass three checks before being accepted:
  1. Reachable, and not a redirect to a parking/registrar page.
  2. Not a parking/placeholder page by content -- matched on strong signals
     ("domain is for sale", "buy this domain", etc.), NOT bare substrings like
     "sedo" or "godaddy" (both are known false-positive triggers from this
     project's prior website-reachability audit -- they collide with ordinary
     text on real sites).
  3. The organization's name (or a distinctive token from it) actually appears
     in the page's title, meta description, or body -- catches a real-but-wrong
     site (different org, similar name).

Anything that fails any check, or has no usable candidate at all, is written to
a review file instead of being silently dropped or silently included.

THIS SCRIPT IS SAMPLE-ONLY BY DEFAULT. It never writes to community_resources.json.
Output always goes to tools/logs/website_finder_*.json / .log for human review.

Usage:
    python3 tools/find_websites_by_address.py --sample 100
"""
import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from ddgs import DDGS
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "community_resources.json"
LOG_DIR = ROOT / "tools" / "logs"

PARKING_SIGNALS = [
    "domain is for sale", "buy this domain", "this domain may be for sale",
    "domain name is parked", "domain has expired", "renew your domain",
    "this web page is parked", "domain parking", "future home of something quite cool",
    "the sponsored listings displayed above are served",  # classic Sedo parking text
]

STOPWORDS = {"the", "of", "for", "and", "inc", "llc", "foundation", "center", "centre",
             "association", "society", "autism", "a", "an"}

# Directory/aggregator/data-broker domains that legitimately contain an org's
# name (so the name-token check alone can't reject them) but are NOT the org's
# own site. First block (through govserv.org) is empirically confirmed -- these
# actually appeared as false "verified" hits in the 2026-09-25 100-entry test
# run (tools/logs/website_finder_verified_20260925_115616.json), concentrated
# in the NPI/small-provider segment. The rest is the same category of site
# (generic business/health/nonprofit directory, not a specific org's registered
# domain) added preemptively -- same reasoning as npino.com/npidb.org/
# npiprofile.com all being the same NPI-directory family.
AGGREGATOR_DOMAINS = {
    "medicarelist.com", "ehealthscores.com", "npino.com", "findabatherapy.org",
    "findabaproviders.com", "bizapedia.com", "nonprofitlist.org", "govserv.org",
    "psychologytoday.com",
    "npidb.org", "npiprofile.com", "healthgrades.com", "wellness.com",
    "zocdoc.com", "mapquest.com", "manta.com", "chamberofcommerce.com",
    "local.com", "superpages.com", "dnb.com", "opencorporates.com",
    "yelp.com", "yellowpages.com",
    # Round 2 (2026-09-25): observed live in the re-test after the first
    # blocklist pass, not caught by it -- this ABA-therapy-provider niche
    # turns out to have its own whole ecosystem of small-business/health-
    # provider directory sites, so this list needs to keep growing, not just
    # be "big enough" once. Removing these alone only moved precision from
    # ~50% to ~54-58% (see tools/logs and HANDOFF.md), not a full fix.
    "opennpi.com", "opengovus.com", "findglocal.com", "findaba.net",
    "findhealthclinics.org", "providerspark.com", "spectrumheart.com",
    "abacarenetwork.com", "abahub.org", "mentalhealthus.org",
    "autismlifeandliving.org", "raisingbrilliance.org", "inclusiveprogramsguide.com",
    "volunteersanantonio.org", "atlantaparent.com", "alabamafamilycentral.org",
    "linkedin.com", "facebook.com",
}


def is_aggregator(netloc):
    host = netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return any(host == d or host.endswith("." + d) for d in AGGREGATOR_DOMAINS)


def distinctive_tokens(name):
    tokens = re.findall(r"[A-Za-z0-9']+", name.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 2]


def domain_matches_name(netloc, name):
    """True if the candidate's own domain contains a fragment of the org's name --
    aggregators are indexed under their own brand, not the listed org's name, so
    this is a much stronger positive signal than a name mention in page content."""
    host = netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    host_stem = host.split(".")[0].replace("-", "")
    for t in distinctive_tokens(name):
        if len(t) > 3 and t in host_stem:
            return True
    return False


def build_queries(name, address, country):
    city = ""
    if address:
        parts = [p.strip() for p in address.split(",")]
        if len(parts) >= 2:
            city = parts[-2] if not parts[-1].replace(" ", "").isdigit() else (parts[-3] if len(parts) >= 3 else parts[-2])
    loc = " ".join(x for x in [city, country] if x)
    queries = [f"{name} {loc}".strip()]
    queries.append(f"{name} {loc} official website".strip())
    return queries


def fetch_page(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ResourceWebsiteCheck/1.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final_url = resp.geturl()
        raw = resp.read(200_000)
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            text = raw.decode("latin-1", errors="ignore")
        return final_url, text


def verify_candidate(url, org_name):
    if is_aggregator(urlparse(url).netloc):
        return False, f"known aggregator/directory domain: {urlparse(url).netloc}"

    try:
        final_url, html = fetch_page(url)
    except Exception as e:
        return False, f"unreachable: {e}"

    parsed = urlparse(final_url)
    if is_aggregator(parsed.netloc):
        return False, f"redirected to known aggregator/directory domain: {parsed.netloc}"
    if any(bad in parsed.netloc.lower() for bad in ["sedoparking.com", "godaddy.com/domain", "afternic.com", "dan.com"]):
        return False, f"redirected to known parking host: {parsed.netloc}"

    lower_html = html.lower()
    for signal in PARKING_SIGNALS:
        if signal in lower_html:
            return False, f"parking-page content signal: {signal!r}"

    tokens = distinctive_tokens(org_name)
    if not tokens:
        return False, "no distinctive name tokens to verify against"
    hits = sum(1 for t in tokens if t in lower_html)
    if hits == 0:
        return False, f"none of the org's name tokens ({tokens}) found on page"

    return True, final_url


def find_website(entry):
    """Collect every candidate that passes verify_candidate (across both query
    variants) instead of returning on the first pass, then rank by whether the
    candidate's own domain contains a fragment of the org's name -- a much
    stronger positive signal than a name mention in page content, since
    aggregators are indexed under their own brand, not the listed org's name."""
    name = entry.get("name", "")
    queries = build_queries(name, entry.get("address", ""), entry.get("country", ""))
    tried = []
    passing = []
    for q in queries:
        try:
            results = DDGS().text(q, max_results=5)
        except Exception as e:
            tried.append({"query": q, "error": str(e)})
            continue
        for r in results:
            url = r.get("href") or r.get("url")
            if not url or not url.startswith("http"):
                continue
            ok, detail = verify_candidate(url, name)
            tried.append({"query": q, "candidate": url, "passed": ok, "detail": detail})
            if ok:
                passing.append(url)
        time.sleep(1)  # be polite between queries

    if not passing:
        return None, tried

    passing.sort(key=lambda u: not domain_matches_name(urlparse(u).netloc, name))
    return passing[0], tried


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=100)
    args = ap.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    data = json.load(open(DATA_FILE, encoding="utf-8"))
    missing = [d for d in data if not d.get("website")]
    print(f"{len(missing)} entries missing a website (out of {len(data)} total)")

    # Mix source types for a representative sample: some NPI (US), some non-US registries.
    npi_like = [d for d in missing if d.get("source", "").lower().find("npi") != -1 or d.get("entity_type") == "provider"]
    other = [d for d in missing if d not in npi_like]
    half = args.sample // 2
    sample = npi_like[:half] + other[: args.sample - min(half, len(npi_like))]
    sample = sample[: args.sample]
    print(f"Sample: {len(sample)} entries ({sum(1 for s in sample if s in npi_like)} NPI-like, rest other sources)")

    verified = []
    review = []

    for n, entry in enumerate(sample, 1):
        url, tried = find_website(entry)
        if url:
            verified.append({"name": entry.get("name"), "address": entry.get("address"), "website": url})
            print(f"  [{n}/{len(sample)}] {entry.get('name')!r}: VERIFIED {url}")
        else:
            review.append({"name": entry.get("name"), "address": entry.get("address"), "attempts": tried})
            print(f"  [{n}/{len(sample)}] {entry.get('name')!r}: no verified candidate ({len(tried)} attempts)")

        if n % 20 == 0:
            print(f"    -- progress: {n}/{len(sample)}, {len(verified)} verified so far --")

    ts = time.strftime("%Y%m%d_%H%M%S")
    verified_path = LOG_DIR / f"website_finder_verified_{ts}.json"
    review_path = LOG_DIR / f"website_finder_review_{ts}.json"
    json.dump(verified, open(verified_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(review, open(review_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"\n{len(verified)} verified, {len(review)} flagged for review")
    print(f"Verified: {verified_path}")
    print(f"Review:   {review_path}")
    print("\nNothing was written to community_resources.json -- this is a sample-only test run.")


if __name__ == "__main__":
    main()
