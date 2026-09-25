"""
Re-check the 23 entries the first audit_legacy_sources.py pass left UNVERIFIED.
Several of the failures were tooling artifacts, not real evidence gaps: this
machine's Python doesn't use certifi's CA bundle by default (spurious SSL
verify failures on real sites), and running 10 concurrent requests triggered
real per-site rate-limiting (429s) that looked like "dead" sites. This script
fixes both (proper CA bundle, sequential with backoff) and re-checks only
those 23, sequentially and politely, before accepting any of them as still
unverified.
"""
import json
import ssl
import time
import certifi
from pathlib import Path
from urllib.parse import urlparse
import urllib.request

from audit_legacy_sources import (
    check_existing_website, independent_search_evidence, distinctive_tokens,
    PARKING_SIGNALS, is_aggregator, fetch_page as _orig_fetch_page,
)

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "tools" / "logs"

SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def fetch_page(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ResourceAudit/1.0)"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        final_url = resp.geturl()
        raw = resp.read(200_000)
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            text = raw.decode("latin-1", errors="ignore")
        return final_url, text


def check_website_patient(url, name, retries=3):
    last = None
    for attempt in range(retries):
        try:
            final_url, html = fetch_page(url)
        except Exception as e:
            last = ("dead", f"unreachable: {e}")
            if "429" in str(e) or "403" in str(e):
                time.sleep(6 * (attempt + 1))
                continue
            return last
        parsed = urlparse(final_url)
        if is_aggregator(parsed.netloc):
            return "aggregator", f"resolves to known aggregator/directory: {parsed.netloc}"
        lower_html = html.lower()
        for signal in PARKING_SIGNALS:
            if signal in lower_html:
                return "dead", f"parking-page content signal: {signal!r}"
        tokens = distinctive_tokens(name)
        if not tokens:
            return "no_match", "no distinctive name tokens to check"
        hits = sum(1 for t in tokens if t in lower_html)
        if hits == 0:
            return "no_match", f"none of the org's name tokens {tokens} found on the page"
        return "ok", final_url
    return last


def search_patient(name, address, retries=3):
    for attempt in range(retries):
        found_any, verified, detail = independent_search_evidence(name, address)
        if detail != None and "search error" not in detail:
            return found_any, verified, detail
        time.sleep(5 * (attempt + 1))
    return None, False, "search backend unavailable after retries"


def main():
    logs = sorted(LOG_DIR.glob("audit_legacy_sources_*.json"))
    latest = logs[-1]
    data = json.load(open(latest))
    unverified = data["unverified"]
    print(f"Re-checking {len(unverified)} previously-unverified entries from {latest.name}, patiently...")

    results = []
    for n, entry in enumerate(unverified, 1):
        name = entry["name"]
        address = entry.get("address", "")
        source = entry.get("source")
        # need the website field again -- re-pull from community_resources.json
        cr = json.load(open(ROOT / "community_resources.json"))
        match = next((d for d in cr if d.get("name") == name and d.get("source") == source), None)
        website = match.get("website") if match else None

        if website:
            verdict, detail = check_website_patient(website, name)
            if verdict == "ok":
                results.append({"name": name, "bucket": "VERIFIED", "evidence": f"re-check: own website reachable and matches ({detail})"})
                print(f"  [{n}/{len(unverified)}] {name!r}: NOW VERIFIED via website")
                time.sleep(1)
                continue
        else:
            verdict, detail = None, None

        found_any, verified, sdetail = search_patient(name, address)
        if verified:
            results.append({"name": name, "bucket": "VERIFIED", "evidence": f"re-check: {sdetail}"})
            print(f"  [{n}/{len(unverified)}] {name!r}: NOW VERIFIED via search")
        elif found_any is False:
            results.append({"name": name, "bucket": "CLEARLY_BAD", "evidence": f"re-check: website {verdict or 'missing'} ({detail}) AND zero independent search results after retries"})
            print(f"  [{n}/{len(unverified)}] {name!r}: STILL CLEARLY_BAD")
        else:
            results.append({"name": name, "bucket": "UNVERIFIED", "evidence": f"re-check: website {verdict}({detail}); search: {sdetail}"})
            print(f"  [{n}/{len(unverified)}] {name!r}: still unverified ({sdetail})")
        time.sleep(2)

    still_v = [r for r in results if r["bucket"] == "VERIFIED"]
    still_u = [r for r in results if r["bucket"] == "UNVERIFIED"]
    still_b = [r for r in results if r["bucket"] == "CLEARLY_BAD"]
    print(f"\nRe-check results: {len(still_v)} now VERIFIED, {len(still_u)} still UNVERIFIED, {len(still_b)} CLEARLY_BAD")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out = LOG_DIR / f"recheck_unverified_{ts}.json"
    json.dump(results, open(out, "w"), indent=2)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
