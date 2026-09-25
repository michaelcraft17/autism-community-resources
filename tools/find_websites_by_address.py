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


def distinctive_tokens(name):
    tokens = re.findall(r"[A-Za-z0-9']+", name.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 2]


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
    try:
        final_url, html = fetch_page(url)
    except Exception as e:
        return False, f"unreachable: {e}"

    parsed = urlparse(final_url)
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
    queries = build_queries(entry.get("name", ""), entry.get("address", ""), entry.get("country", ""))
    tried = []
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
            ok, detail = verify_candidate(url, entry.get("name", ""))
            tried.append({"query": q, "candidate": url, "passed": ok, "detail": detail})
            if ok:
                return url, tried
        time.sleep(1)  # be polite between queries
    return None, tried


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
