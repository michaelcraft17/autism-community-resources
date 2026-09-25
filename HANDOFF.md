# Handoff notes — autism-community-resources

Operational/engineering reference for whoever (human or Claude) picks this project up next.
The public-facing feature overview is in `README.md`; this file is about how the project
actually works under the hood and what to watch out for.

## What this is

A single-file React app (`index.html`, in-browser Babel, no build step) that maps and lists
autism/special-needs community resources worldwide. Deployed via GitHub Pages from `main` at
**autismcommunityorg.org**. Repo: `github.com/michaelcraft17/autism-community-resources`.

## Data pipeline

```
community_resources.json  (canonical flat JSON array, ~70k entries)
        │  node gen_community_data.js
        ▼
community_data.js          (window.communityData = [...], loaded via <script> tag)
        │  read by useCommunityData() / shapeAll() in index.html
        ▼
the live app
```

**Always regenerate `community_data.js` after editing `community_resources.json`:**
```
node gen_community_data.js
```
It must emit `window.communityData = [...]` (a global, not a bare `const`) — index.html loads
it as a classic script and reads `window.communityData` off it. A bare `const` silently fails
and the site falls back to 6 hardcoded sample resources with no visible error. This exact bug
took the site down once already (fixed in commit `f3ae20e`); `tools/regen_community_data_js.py`
does the same thing in Python if that's more convenient, and has the same requirement.

### Data harvesting tools (all in `tools/`, all free/local, no API keys)

Preference order, most to least reliable — **official structured datasets beat LLM narration
every time**, verified concretely this session (LLM narration had a ~50%+ fabricated-URL rate;
government/encyclopedic structured sources were ~95%+ clean):

- `npi_taxonomy_fetch.py` → `_prefilter.py` → `_geocode.py` → `_merge.py` — 4-step, resumable
  pipeline against the US NPI Registry (npiregistry.cms.hhs.gov). Read the docstring in
  `npi_taxonomy_fetch.py` first; it documents real gotchas (taxonomy_description matching
  quirks, the 1000-result API ceiling, a known "whole chunk silently dropped on geocoder
  timeout" issue and its workaround).
- `cqc_uk_fetch.py` — UK's official Care Quality Commission care directory (free CSV,
  updated weekly, Open Government Licence). Only covers England; Scotland/Wales/NI have
  separate regulators (Care Inspectorate, CIW, RQIA) with presumably similar open data,
  not yet built.
- `wikidata_autism_fetch.py` (+ `wikidata_country_fetch.py` for a specific country list via
  native-language search terms) — searches Wikidata for real-world autism/disability orgs
  across ~6 organization classes (nonprofit, NGO, charity, advocacy group, foundation,
  disability association), globally, in one pass. Broad but shallow (only orgs notable enough
  for a Wikidata entry) — complements a country registry like the CQC one rather than
  replacing it.
- `autism_europe_members_fetch.py` — Autism-Europe's own 2023 member-directory PDF,
  hand-transcribed (no API exists), covering ~35 European countries' national/regional
  umbrella organizations. Not deep (one or a handful of orgs per country) but a solid,
  official floor for any European country before reaching for anything else.
- `france_rna_fetch.py` — France's RNA (Répertoire National des Associations), the
  Ministry of Interior's official registry of all 2.26M declared associations, queried via
  its Opendatasoft mirror's real search API (the raw data.gouv.fr files are only bulk ZIPs,
  no keyword search). Added 2,328 active associations matching autisme/autiste/autistes in
  one pass — by far the deepest single source this project has used for any country outside
  the US/UK. Comes with pre-computed coordinates, no separate geocoding needed. Known quirk:
  ~37% of description text has an upstream accented-character encoding artifact in older
  records — see the script's docstring, not worth chasing a fix.
- `netherlands_anbi_fetch.py` — Netherlands' ANBI tax-status register (Belastingdienst,
  CC-0, ~55K orgs, weekly-refreshed bulk XML download, not an API). Much narrower than
  France's RNA (ANBI is a specific tax election, not "any declared association") — only
  ~20 real autism-keyword matches — and has no street address or purpose/mission text in the
  schema, just name/alias/city/website, so entries are city-centroid geocoded. Worth checking
  whether other EU countries have an equivalent official charity-tax registry before assuming
  France's RNA scale is typical — it may not be.
- `czech_ares_fetch.py` — Czech Republic's ARES (Administrative Register of Economic
  Subjects), a modern free REST/JSON search API, no key. Added 7 clean organizations,
  including the national "Národní ústav pro autismus." Response includes a pre-formatted
  address string (`sidlo.textovaAdresa`), so no address assembly needed.
- `estonia_ariregister_fetch.py` — Estonia's e-Business Register (Ariregister, run by RIK),
  free JSON autocomplete API. Added 8 organizations including the national federation and
  several regional associations — unusually deep coverage for a country of 1.3M. Needs a
  descriptive User-Agent header or the endpoint 403s (a basic bot filter, not a real block).
  Its address format (county/parish/village hierarchy, e.g. "Harju maakond, Tallinn,
  Kesklinna linnaosa, Jõe tn 5") is too granular for Nominatim as one string — the script
  retries with progressively fewer trailing comma-segments until one resolves. Expanded +4 in
  a follow-up pass: the original term list ("autism"/"autismi"/"autistlik") turned out too
  narrow, missing other Estonian grammatical forms of "autist" (person with autism) —
  "autistide" (genitive/partitive) surfaced **a second national organization entirely missed
  the first time**, "Eesti Autistide Liit" (genuinely distinct from the already-found "Eesti
  Autismiliit" — the former traces back to a self-advocacy group formerly named "Eesti
  Aspergerite Ühing," found via a web search after an ambiguous registry hit, not the registry
  search itself). One ambiguous match ("Autist OÜ," a private company with no corroborating
  evidence of relevance) excluded by name, same discipline as Bulgaria's "АСПЕР" exclusion.
- `latvia_ur_fetch.py` — Latvia's Register of Enterprises (Uzņēmumu reģistrs) open-data bulk
  CSV of every association/foundation (regcode;name;type;area_of_activity). A genuine full
  registry dump, found via data.gov.lv's CKAN dataset catalog rather than a name-search API.
  Added 7 organizations. Same false-positive class as Belgium/Netherlands: Latvian
  "starptautisks" (international) contains "autis" as a coincidental substring
  ("st-ARPT-AUTIS-ka") — excluded explicitly. No street address in the dataset; a few
  entries name a city in their own org name (e.g. "Daugavpils autisma centrs"), geocoded to
  that city, the rest are placeless.
- `slovenia_ajpes_fetch.py` — Slovenia's AJPES ePRS business register. Its real search
  endpoint (`ajax.asp?method=getNaziv`) was found the same way Belgium's KBO param set was —
  driving the live search form once with Playwright and reading the network log. It's a
  *prefix* autocomplete, not substring search, which matters for a heavily-declined language:
  the dictionary form "avtizem" finds nothing, since the one real match is named starting
  with a declined form ("AVTIZMU..."). Only one organization found for the whole country;
  shipped as a hand-authored placeless entry rather than building out full detail-page
  scraping for a single result.
- `wikidata_country_fetch.py` — expanded 2026-09-24 from 5 to 18 target countries (added
  Denmark, Croatia, Greece, Iceland, Luxembourg, Serbia, Slovakia, Bulgaria, Cyprus, Romania,
  Turkey, Ukraine, Andorra) to backfill countries whose own government registry is either
  unreachable from this sandbox or has no free search/bulk-export API. Net new: Denmark
  (+1, with real coordinates), Germany (+1). No new hits for the other 11 added countries —
  a real finding (Wikidata simply has no notability-threshold org tagged to them yet), not a
  bug; don't re-run this exact sweep expecting different results without a genuinely
  different technique.
- `norway_brreg_fetch.py` — Norway's Bronnoysund Register Centre (Enhetsregisteret), the
  official national registry of every business/association/foundation in Norway. Free, no key.
  Deepest single-country win since France's RNA: captured the national autism association
  (Autismeforeningen i Norge) plus all ~19 of its regional chapters (Lokallag/Fylkeslag) as
  separate registered legal entities, with full street addresses. Same fuzzy-search quirk as
  Belgium/Netherlands ("autist" as a query returns hundreds of unrelated "AUGUST ..." names via
  edit-distance matching, not substring) — filtered client-side. Also excludes entities flagged
  bankrupt/winding-up, and a Norwegian-specific dead-entity pattern: sole-proprietorships whose
  owner died ("... Inngår I Dødsbo" — estate in probate). Expanded in a follow-up "Asperger
  sweep" pass (+3: "Aspergerforeningen I Norge," "Aspergerforeldre," and an individual
  practitioner) after adding "asperger" as a search term and checking each entity's
  `historiskeNavn` (historical name) list, not just its current name.
- `finland_ytj_fetch.py` — Finland's PRH Business Information System (YTJ), same tier of
  official registry. Much smaller country, much smaller yield (2 net-new active orgs: the
  Autism Foundation and the national Autism Spectrum Association) — Finland doesn't appear to
  register regional chapters as separate legal entities the way Norway does. Expanded +1 in the
  same follow-up pass: "NeuroMental Oy," a real diagnostic clinic whose *current* name doesn't
  contain "asperger" at all, but whose registered auxiliary/trade name ("Helsingin Asperger
  Center") does -- YTJ tracks these separately per company, so matching now checks every
  registered name, not just the primary one.
- `switzerland_zefix_fetch.py` — Switzerland's Zefix (Zentraler Firmenindex), the federal
  commercial registry, via an unauthenticated JSON endpoint the public `www.zefix.ch` search UI
  itself calls (`POST /ZefixREST/api/v1/firm/search.json`, `GET /ZefixREST/api/v1/firm/<id>.json`)
  — a genuinely new find 2026-09-25, not documented before. HANDOFF previously said Zefix
  "requires authentication (401 without credentials)"; that's true of the separate *documented*
  developer API at `www.zefix.admin.ch`, but the live site's own endpoint, on a different host
  (`www.zefix.ch`), works with a plain request and a descriptive User-Agent — same class of
  discovery as Belgium's KBO PDF export or Greece's GEMI publicity API (the public site's own
  real endpoint, not the gated admin one). `searchType: "exact"` is misleadingly named — it's
  actually a substring match. Querying the German/French/English shared root "autis" plus
  "asperger" separately (Italian "autismo," German "autistisch," French "autistique" all
  returned zero) gave 18 raw hits; excluded 3 real false positives after checking each one's
  registered `purpose` text (a car-trade business named "Autisä," a clothing brand named
  "AUTISM," and an HR-consultancy "asperger gmbh" unrelated to Asperger's) and 2 entities in
  `IN_AUFLOESUNG` (liquidation) status — same exclusion class as Norway's `konkurs`/
  `underAvvikling`. Net: **13 active, genuinely autism/Asperger-related Swiss entities**, full
  street addresses from the detail endpoint, no separate address-assembly gotcha.
- `bulgaria_companybook_fetch.py` — Bulgaria's Commercial Register / Register of Non-Profit
  Legal Entities, via a **third-party API** (CompanyBook.bg), not a direct government source
  — the first and so far only fetcher in this project to use one. Justified because
  CompanyBook's own FAQ states its data "comes from the daily publications of the Registry
  Agency, uploaded to the [Ministry of e-Governance] open data website... under the CC-BY
  license" (i.e. it republishes official government open data), and every direct path to
  Bulgaria's own systems was independently confirmed dead — see HANDOFF's "Ruled out" section
  (`data.egov.bg` 403s even for Googlebot/Bingbot; the Registry Agency's own portal has no
  free entity search). Requires a free API key via `COMPANYBOOK_API_KEY` (sign up at
  companybook.bg; 100 req/day free tier, easily enough for this script). The account used
  for this project was created 2026-09-24 under changcheng875@gmail.com — the credentials
  (email/password) are known to the site owner, not stored in this repo; the API key itself
  is never hardcoded or committed, only ever passed via the `COMPANYBOOK_API_KEY` env var.
  Added 13 organizations, all active (started at 9, then +4 in a follow-up pass -- see below).
  Two real address-geocoding gotchas fixed here, worth knowing about for any future Bulgarian
  source: (1) the registry's precise street-level address routinely fails to resolve in
  Nominatim as one string (same class of issue as Estonia's hierarchical addresses) -- falls
  back to city-level; (2) the API's own `settlement` field carries a "гр."/"с." (town/village)
  type-prefix that *also* breaks Nominatim even at the fallback step (e.g. "гр. Панагюрище"
  resolves to nothing, but plain "Панагюрище" resolves fine) -- stripped explicitly.
  Two more real bugs found and fixed in a follow-up pass: (3) the search API's own status
  filter (`status=true` in the request) doesn't mean "status field equals N" -- a confirmed-
  real, currently-registered foundation ("Фондация Аспергери") came back with an undocumented
  status "E", which the first version of this script's client-side `== "N"` check wrongly
  dropped. Only the one documented dead status ("L", liquidated) is excluded now, not a
  whitelist of "N" alone -- this alone recovered 3 more real organizations. (4) the name
  search is fuzzy/prefix-based, not strict substring, same class of issue as Norway's
  "autist"-matches-"August" -- confirmed by querying "Аспергер" (Asperger) and getting back
  "АСПЕР", an unrelated 5-letter company name; a client-side substring check on the result
  name was added. Also added "Аспергер" itself as a search term (Asperger's, now considered
  part of the autism spectrum, wasn't covered by the original autism-root terms) after finding
  it via a follow-up "is there more here?" pass -- worth remembering for other countries too:
  searching only the literal word "autism" in the local language misses Asperger-named orgs.
- `greece_gemi_fetch.py` — Greece's GEMI (General Commercial Registry), via its public
  "Publicity" search portal (`publicity.businessportal.gr`) — a completely different, working
  domain from every Greek domain previously ruled out (`data.gov.gr`, `opendata-api.
  businessportal.gr`, `businessregistry.gr`, `www.gemi.gr` itself, all unreachable). Two free
  JSON endpoints found via one-time Playwright discovery: `/api/autocomplete/<term>` for name
  search, `/api/company/details` (POST `{"query":{"arGEMI":"<id>"},"token":null}`) for the
  full record including a real street address. The page preloads a reCAPTCHA script, which
  looked like it might gate the details call — it doesn't; `"token":null` works fine and no
  challenge ever triggered. Added 3 organizations.
- `slovakia_rpo_fetch.py` — Slovakia's RPO (Register of Legal Persons, run by the
  Statistical Office), the *current* unified master registry — a different, working system
  from the one HANDOFF previously ruled out (the open-data catalog's "Register neziskových
  organizácií" dataset points to `ives.minv.sk`, a legacy portal that 503s consistently; RPO
  at `rpo.statistics.sk` is separate and current). Needs a session cookie first — a plain
  request 401s until you POST to `/rpo/rest/auth/user`, which mints a `JSESSIONID`, same
  pattern as a browser's own first-load handshake. Its full-text search matches an org's
  stated purpose, not just its name. Added **33 organizations** — a genuinely deep national
  support network (many are regional branches of "Spoločnosť na pomoc osobám s autizmom,"
  one per city), the second-deepest addition of this whole "single-listing countries" effort
  after Ukraine. Expanded +1 in a follow-up pass: "ASPERGER KLUB," found after adding
  "asperger" as a search term.
- `cyprus_registry_fetch.py` — Cyprus's official Register of Associations, Foundations,
  Federations and Unions, published as a CSV on data.gov.cy (found via the portal's own
  Drupal `/search?s=<term>` endpoint, not a CKAN API — this portal isn't CKAN, and
  `/api/3/action/...` paths 404 here). Added 4 organizations across 4 districts, geocoded to
  each district's main city (no street address in the source). One 5th match excluded: still
  "ΥΠΟ ΕΞΕΤΑΣΗ" (under review), not yet an approved registration.
- `ukraine_edr_fetch.py` — Ukraine's Unified State Register of Legal Entities, Individual
  Entrepreneurs, and Public Formations, the full official bulk export on data.gov.ua. By far
  the largest single file this project has ever processed: a ~319MB zip containing one
  ~3.2GB windows-1251-encoded XML covering every legal entity in the country, streamed and
  filtered record-by-record (not loaded into memory, not DOM-parsed). The single deepest
  addition of this whole "single-listing countries" round: **41 active organizations** (2
  more excluded: terminated / being terminated). No address field exists anywhere in this
  dataset at all — a plausible deliberate wartime omission from the public export, not a gap
  specific to this project; entries are placeless except the handful whose own registered
  name states a city/oblast. Caught a real bug while building this (see
  `merge_new_resources.py` below) and a real gotcha: naive `bytes.lower()` does not
  Unicode-case-fold multi-byte UTF-8 Cyrillic, so an early version of the keyword match
  silently found only 1 of 43 raw hits — fixed by decoding to `str` before `.lower()`.
- **Asperger-sweep round 2 (2026-09-25)** — went back through the fetchers the first sweep
  (2026-09-24) hadn't reached yet:
  - `france_rna_fetch.py`: added "asperger" to the OR-combined query (was "autisme OR autiste
    OR autistes", now adds "OR asperger"). "asperger" alone returns 111 raw hits on the RNA's
    Opendatasoft API; 21 are net-new active associations not already matched by the autism-root
    terms (real dedicated orgs: "ASPERGER VOSGES," "ASPERGER ACCUEIL," "APIPA-ASPERGER-TSA," a
    few others whose connection is looser but kept, same tolerance as the root query's own
    false-positive rate). **+21**.
  - `netherlands_anbi_fetch.py`: added "asperger"/"aspergers" to `KEYWORDS`. Confirmed by
    parsing the cached `anbi.xml` directly: **zero** matches of any kind for either term in the
    whole ~55K-org register — a real negative finding (unlike France/Norway/Finland/Belgium/
    Switzerland, no Dutch ANBI-registered charity has "asperger" anywhere in its name or alias),
    not a bug; ANBI already had no separate historical-name field to miss a match through.
  - `belgium_kbo_fetch.py`: **not swept**. The PDF-export param set that made the original
    "autisme" query work (`FIXED_PARAMS` mentioned in the docstring) was never saved to the
    script itself — it was captured once via a live Playwright session and used directly, not
    preserved as reusable code. Several plausible param guesses (`actionLu=Zoeken`,
    `submit=Zoeken`, `nummerType=`) all returned the plain search *form* page, not a PDF, for
    `searchWord=asperger` — meaning a required param is still missing. Needs a fresh Playwright
    session to re-capture the working param set (unavailable in this sandbox this round, no
    `playwright` package installed) before this can be sept.
  - `italy_runts_fetch.py`: **not swept**. Same root cause as Belgium — RUNTS has no JSON API,
    only a ViewState-bound ASP.NET postback form, and needs a live Playwright session to drive
    it. Not attempted without Playwright available.
  - `greece_gemi_fetch.py`: retried plain (no query changes) — still unreachable from this
    sandbox, 3/3 timeouts (`curl` exit 28, connect timeout). Consistent with the prior session's
    "intermittently unreachable" note; not yet confirmed as a real block, just still flaky from
    here. Worth another retry later, still not ruled out.
  - Czech Republic, Latvia, Slovenia, Ukraine, Cyprus, Estonia, Norway, Finland, Slovakia,
    Bulgaria were already swept in the first round (see "Current state" below) — all 15 built
    country fetchers have now had an Asperger-sweep attempt, 4 successfully expanded
    (France, Norway, Finland, Slovakia this round/last), 1 confirmed zero-yield (Netherlands),
    2 still blocked pending Playwright (Belgium, Italy), 1 still network-flaky (Greece).
- New country investigated and added 2026-09-25: **Switzerland** (Zefix, +13 — see fetcher
  entry above). Poland, Portugal, and Austria investigated and ruled out (see "Ruled out" below).
- `tools/scheduled_refresh.sh` — new unattended-refresh script (2026-09-25). Re-runs the 12
  cheapest official-registry fetchers (excludes Italy's flaky Playwright scrape, Ukraine's
  ~3.2GB bulk download, and Bulgaria's API-key-gated one unless `COMPANYBOOK_API_KEY` is set),
  then `merge_new_resources.py` and `node gen_community_data.js`, and logs to
  `tools/logs/refresh_<timestamp>.log`. **Never commits or pushes** — leaves the working-tree
  diff for a human/Claude to review and commit by hand, per this repo's standing rule. Zero
  LLM/token cost per run (plain HTTP + JSON parsing). Not yet wired to any actual scheduler
  (cron/launchd) — that's a deliberate choice left to the site owner, since it would create
  uncommitted local changes unattended if run on a timer without someone reviewing the diff.
- `merge_new_resources.py` — generic merge step: dedupes any `new_resources_*.json` file in
  the repo root against `community_resources.json` (by normalized name and website domain)
  and appends the rest. Run this after any of the fetchers above, then regenerate
  `community_data.js`. **Bug fixed 2026-09-24**: `norm_name()`'s dedup key used to strip
  every character outside ASCII `[a-z0-9]`, which silently collapsed *any* non-Latin-script
  name (Cyrillic, Greek, CJK, ...) to an empty or near-empty key — meaning distinct
  organizations with different Cyrillic/Greek names were treated as duplicates of each
  other and dropped. Caught because it ate 40 of 41 genuinely distinct Ukrainian orgs and 1
  of 4 Cyprus orgs on first merge. Fixed to use Python's Unicode-aware `str.isalnum()`
  instead — confirmed via a full rerun that this only *adds* previously-lost non-Latin
  entries and doesn't change any existing Latin-script dedup behavior. Any future
  non-Latin-script source should be safe against this now, but past merges that used the old
  function are not retroactively recoverable (their source `new_resources_*.json` scratch
  files are long gone) — if a future Chinese/Japanese/Korean/Arabic sweep seems to be
  under-yielding, this class of bug is worth checking for again.

**Ruled out, don't re-attempt without a new angle:**
- 2026-09-24 "single-listing countries" pass, three rounds. Reachability tested via both plain
  `curl` and a real Playwright browser (the browser's network stack occasionally succeeds
  where curl gets a `000`, as happened for Latvia's `data.gov.lv` and Croatia's/Cyprus's
  `data.gov.hr`/`data.gov.cy` open-data portals — always retry a `000` with a real browser
  before ruling a source out). Also learned: a country ruled out because its *one obvious*
  registry was dead/unreachable can still have a second, completely different official system
  that works (Ukraine, Slovakia) — check for a second domain/agency before giving up.
  - **Cyprus, Ukraine, Greece, and Slovakia are no longer single-listing** — see their fetch
    scripts above (`cyprus_registry_fetch.py`, `ukraine_edr_fetch.py`, `greece_gemi_fetch.py`,
    `slovakia_rpo_fetch.py`). Greece in particular had *every* domain tried in round 2 turn
    out unreachable (`data.gov.gr`, `opendata-api.businessportal.gr`, `businessregistry.gr`,
    `www.gemi.gr`) before `publicity.businessportal.gr` — a differently-named domain for the
    same GEMI registry — worked cleanly in round 3.
  - Genuinely unreachable from this sandbox, confirmed with an explicit WAF block page (not
    just a timeout) where noted: Germany's `vereinsregister.de`, Denmark's
    `distribution.virk.dk`/`datacvr.virk.dk` (explicit 403 from Playwright), Croatia's live
    registry `registri.uprava.hr` (its open-data portal `data.gov.hr` *is* reachable, see
    below), Serbia's `pretraga2.apr.gov.rs` and `www.apr.gov.rs` (explicit "The URL you
    requested has been blocked" page), Turkey's `dernekler.gov.tr`, and **Lithuania's**
    `data.gov.lt`/`get.data.gov.lt` (same explicit block page/message as Serbia — confirmed
    via both curl, which showed a plain 500, and Playwright, which showed the real block-page
    title) and `www.registrucentras.lt` (403). Same class of finding as China's DNS-
    unreachable registry — would need testing from a different network to know if it's
    sandbox-specific or a real geo-restriction.
  - Reachable, real registry dataset found, but missing the field needed to search or geocode
    by name: **Croatia**'s `data.gov.hr` (correct CKAN path is `/ckan/api/3/action/...`, not
    `/api/3/action/...` — worth remembering for other CKAN-based portals) hosts an official
    "Registar udruga Republike Hrvatske" dataset, but its published resources are only
    "Djelatnosti" (activity codes keyed by an internal ID), "Osobe" (representatives' names),
    and "CTS" (classification tree) — the organization *name* field itself isn't in the open
    data, only on the unreachable live portal. Checked FINA (fina.hr, Croatia's financial
    agency, which runs the actual non-profit financial-reporting register) too — no
    name-searchable NPO registry link found on its main site nav.
  - Reachable, explicit block/CAPTCHA (no evasion attempted, ruled out on principle):
    **Romania**'s ONRC (`www.onrc.ro`) returns an explicit WAF rejection page ("The requested
    URL was rejected... support ID: ..." — an F5 BIG-IP-style block; `data.gov.ro` also times
    out). **Luxembourg**'s LBR company search (`lbr.lu/mjrcs-web-front`) is gated behind a
    live CAPTCHA (`global.frcapi.com/api/v2/captcha/...`, Friendly Captcha) as soon as a
    search is submitted; its open-data catalog (`data.public.lu`) has no NGO-registry dataset.
  - Reachable but no usable free API found despite a real attempt (not just untried):
    **Bulgaria**'s registry portal (`portal.registryagency.bg`) has two dead ends: its
    "VerificationPersonOrg" tool sits behind an OAuth login flow, and its one apparently-free
    search box (`sKey` param, reached from several different nav paths, including the
    "Справки"/Reports section) turns out to search the *portal's own content* (news/help
    pages/templates), not the entity registry itself — "Намерени са 0 резултата" for every
    real company-name query, confirmed by reading the actual response categories.
    `data.egov.bg`/`opendata.government.bg` both return a 403 even with a real browser UA
    (Cloudflare-style block, not a naive filter). **Iceland**'s `skatturinn.is` company search
    requires a browser session/cookie (plain `curl` gets redirected) and, once driven live via
    Playwright, the bare dictionary term "einhverfa" (autism) returned zero results anyway —
    low priority given the population (~380K) even if the session-cookie friction were solved.
  - Andorra: reachable (`govern.ad`, HTTP 500/302 on different paths) but no dedicated
    business/association registry open-data source found at all — very small country (~80K
    people), likely minimal digital registry infrastructure to begin with. Lowest remaining
    priority of the 6 still-single-entry countries.
  - **2026-09-24 round 4** — all 6 remaining countries re-checked with a "find a second,
    different official system" lens (the exact technique that worked for Ukraine/Slovakia/
    Greece). No new wins this round, but each got a genuinely different angle tried and ruled
    out, not a repeat of the same dead domain:
    - **Croatia**: tried the *other* national registry — `sudreg.pravosudje.hr`, the Ministry
      of Justice's commercial COURT register (separate system from the udruga/association
      register). It's reachable and has a real working search form (Oracle APEX, field
      `#P1_NAZIV`), but its "Pravni oblik" (legal form) dropdown only lists company types
      (d.o.o., dioničko društvo, zadruga, etc.) — no "udruga" — and a live search for "autiz"
      correctly returns zero results. Associations genuinely aren't in this register at all;
      they only exist in the unreachable `registri.uprava.hr` system. Confirms Croatia needs
      that exact system reachable, not a workaround.
    - **Romania**: tried ANAF (the tax authority, `www.anaf.ro`, reachable) as a possible
      third angle beyond ONRC/data.gov.ro — but ANAF's public tools are CUI/VAT-lookup by
      already-known fiscal code, not a name-search registry; no bulk NGO dataset found.
      `reonge.just.ro` and `www.just.ro/registrul-national-ong/` (guessed URLs for the
      National NGO Registry) are both dead (connection failure / 404).
    - **Bulgaria**: tried the Ministry of Justice's own domains (`mjs.bg`, `www.justice.
      government.bg`) as a system separate from the Registry Agency portal already ruled out
      — both return a genuine HTTP 500. The Registry Agency's own `/CR/services` page (which
      does list "regisтър на юридическите лица с нестопанска цел" / NPO register as part of
      the same system) renders no bulk-export or distinct search link when read directly.
    - **Lithuania**: no new angle found beyond the already-confirmed WAF block.
    - **Luxembourg**: confirmed via `data.public.lu`'s own search API that querying "RCS" or
      "registre commerce societes" returns zero datasets — there's no bulk alternative to the
      CAPTCHA'd live search.
    - **EU-level fallback tried and ruled out for all remaining EU members at once**: the
      European e-Justice Portal's "Find a company" tool (`e-justice.europa.eu`), which proxies
      national business registers via the EU's BRIS interconnection system — would have been a
      single fix for Croatia/Bulgaria/Romania/Luxembourg/Lithuania if it worked, but it returns
      an explicit 403 from this sandbox, confirmed via both curl and Playwright.
  - **2026-09-24 round 5** — used live web search (not just guessing domain names) to find
    each country's *actual current* system, one level deeper than round 4. Landed on a
    specific, confirmed blocker for every remaining country, not just "untried":
    - **Croatia**: web search surfaced the real current domain — the ministry was renamed and
      the register moved to `registri-npo-mpu.gov.hr` (found via `mpudt.gov.hr`, "Ministarstvo
      pravosuđa, uprave i digitalne transformacije"), a different, working URL from
      `registri.uprava.hr`. It's a slow-loading Vaadin app (needs ~9s wait, not just a
      timeout) but does load and has a real "Naziv udruge" (association name) search field.
      Submitting a search shows a genuine distorted-text CAPTCHA ("Prepišite kontrolni broj") —
      confirmed with a screenshot. Ruled out on principle, no evasion attempted. This is the
      closest any of the 6 has come to working — worth revisiting if a CAPTCHA-solving service
      the user explicitly authorizes ever becomes in-scope for this project (it currently
      isn't).
    - **Luxembourg**: confirmed the LBR does operate a real open-data API separate from the
      CAPTCHA'd consumer search UI, but it's distributed through "i-Hub," a B2B platform aimed
      at fiduciaries/banks/public authorities (per LBR's own press materials) — not a public,
      anonymous, sign-up-and-go API. No public developer-portal URL found on lbr.lu itself.
    - **Bulgaria**: found a legitimate *third-party* option — `companybook.bg`, whose FAQ
      states its data comes from "the daily publications of the Registry Agency, uploaded to
      the [Ministry of e-Governance] open data website... under the CC-BY license" (i.e. it
      republishes official government open data, not scraped). Confirmed via its own API docs:
      real endpoint `GET https://api.companybook.bg/api/v2/companies/search`, but **requires a
      free account sign-up** to get an API key (100 req/day free tier) — no anonymous access.
      Separately reconfirmed `data.egov.bg` (Bulgaria's own open-data portal) is blocked even
      for Googlebot/Bingbot per an independent source, not just this sandbox — a genuine
      site-wide restriction, not something worth re-testing later.
      **Resolved in a follow-up round**: the site owner authorized the sign-up, so this is no
      longer a dead end — see `bulgaria_companybook_fetch.py` above (+9). Bulgaria is out of
      this ruled-out list; left the trail above intact since it explains why a third party was
      used at all and documents the actual data provenance.
    - **Romania**: web search turned up a second official NGO-adjacent register — "Registrul
      de evidență a asociațiilor și fundațiilor" at the Ministry of Finance
      (`mfinante.gov.ro`) — but that domain is unreachable from this sandbox (connection
      failure via both curl and Playwright). Also confirmed via multiple independent sources
      that Romania's actual NGO registry (RAF, held at the Ministry of Justice) has **no online
      search or extract at all as a matter of policy** — extracts must be requested by mail, in
      person, or courier with payment. This isn't a technical block to route around; there is
      no online access to route to.
    - **Lithuania**: reconfirmed the WAF block on the official `get.data.gov.lt` gateway
      mentioned in third-party API docs — same exact block-page title as before.
    - **Andorra**: the government's own "Registre d'Associacions" page is a pure navigation
      stub — no embedded list, table, or download link of any kind, confirmed by reading its
      raw HTML directly.
- **Poland, Portugal, Austria** (2026-09-25 investigation, alongside Switzerland's real win
  above — same "confirm with curl, don't assume" discipline):
  - **Poland**: KRS (Krajowy Rejestr Sądowy)'s official free API
    (`api-krs.ms.gov.pl/api/krs/OdpisAktualny/<krsNumber>`) is a lookup-by-known-number API
    only (confirmed: returns HTTP 400 without a valid KRS number, no name-search parameter
    exists) — not usable for keyword search. The consumer search portal
    (`wyszukiwarka-krs.ms.gov.pl`) is behind Incapsula, confirmed via a real 403 block response
    (`X-Iinfo`/`_Incapsula_Resource` markers), same WAF class as other ruled-out registries —
    no evasion attempted. `dane.gov.pl` (Poland's open-data portal) has no bulk KRS/association
    export dataset (searched via its own API, nothing relevant found).
  - **Portugal**: the RNPC name-check tool (`registo.justica.gov.pt/Empresas/
    Pesquisar-nomes-firmas-ou-denominacoes-existentes`) is reachable but is the same class of
    legacy ASP.NET WebForms page as Italy's RUNTS — `__VIEWSTATE`/`__EVENTVALIDATION`-bound
    postback, no JSON API, needs a live browser session to drive (confirmed by reading the raw
    HTML directly: real hidden form fields present, no discoverable REST endpoint). Not pursued
    without Playwright available this round — same blocker as Belgium/Italy above. Also worth
    noting for later: this specific tool is designed for "is this exact name available"
    name-reservation checking, not general full-text keyword search — even once drivable, it
    may not surface orgs the way a real search API would.
  - **Austria**: the ZVR (Zentrales Vereinsregister)'s public search explicitly states, in its
    own documentation, "only individual queries are permitted; bulk queries... are not
    possible" for data-protection reasons — a stated *policy* restriction, not just a technical
    one. Treated the same as Romania's "no online access as a matter of policy" finding: ruled
    out on principle rather than run even a handful of scripted queries against an explicitly
    no-bulk-queries service. No separate open-data/bulk export found on `data.gv.at` either (a
    quick dataset search turned up nothing at the expected path).
- OpenStreetMap Overpass API — theoretically the most "global" option, but the public
  instance can't handle whole-country or bbox-scoped name-regex searches at any reasonable
  timeout (confirmed via 5+ separate timeouts across France/Japan/bbox attempts). Would need
  per-region tiling (like the NPI pipeline does per-state) to ever be viable — untested.
- NDIS (Australia) — public API only exposes aggregate provider *counts*, not a named/
  addressed provider list, without applying for provider-level API access.
- Free-text GPT-Researcher country reports without a verification pass — see below.
- China's official NGO registry, `xxgs.chinanpo.mca.gov.cn` (Ministry of Civil Affairs'
  National Social Organization Credit Information Disclosure Platform) — `curl` can't even
  resolve the hostname, confirmed both from this project's sandbox *and* from the site
  owner's own residential network (`curl: (6) Could not resolve host`). This is the correct
  official source in principle (would beat Wikidata's near-zero China coverage), but it's
  DNS-unreachable, not just JS-rendered — no scraping/API-discovery technique fixes an
  unresolvable hostname. Would need testing from a network inside mainland China, or a VPN
  with a China exit node, neither of which this project has. `cdpf.org.cn` (China Disabled
  Persons' Federation's public-disclosure portal) untested from a real network yet — same
  domain-family risk, check before investing time.
- GPT-Researcher for China/Russia specifically (2026-09-23 run, both verified via
  `verify_report.py`): 0 usable net-new orgs from either query. China: all 4 named orgs
  (ASC/ARTI/ASN/ACF) were fully fabricated — dead URLs, and searching the real names
  surfaces unrelated entities (a US government agency, an Indian dictionary site, etc.).
  Russia: every "match" verdict was a same-name-different-country collision (US ABA
  providers "Advanced Autism Services"/"Kids ClubABA" that happen to have blogged about
  autism in Russia, not Russian orgs), and the two Russia-sounding names were hallucinated
  near-duplicates of orgs already correctly sourced from the Autism-Europe PDF (see below).
  Don't re-run this exact query shape without a different angle (e.g. a more specific
  region/city, or asking for regulatory registries by name instead of "major organizations").

### Local AI tooling (outside token budget, free to rerun)

- **Ollama + Aider**, set up in this repo: `.aider.conf.yml` (model: `ollama_chat/qwen2.5-coder:7b`),
  `.aiderignore` (blocks the two huge data files from ever entering chat context —
  **never** add `community_resources.json` or `community_data.js` to an Aider chat, it
  blows the model's context and Aider will ask to proceed anyway; decline). Launch via
  `tools/aider-local.sh`. Works fine on small/medium files; **cannot handle `index.html`**
  (~35k tokens alone vs. the model's 32k context) — that one still needs Claude.
- **GPT-Researcher + Ollama + DuckDuckGo**, set up *outside* this repo at
  `~/gpt-researcher-local/` (not tracked here). Free local web research via
  `python3 research.py "query"`. It's genuinely good at finding real organizations by name,
  but qwen2.5-coder:7b reliably **fabricates plausible-but-wrong citation URLs** in its
  References section, and in at least one observed case, copy-pasted one org's entire
  Services/Impact section onto a second org's name with zero citation. `verify_report.py` in
  that same directory auto-checks every citation URL against a fresh independent search after
  each run and flags mismatches — never merge a GPT-Researcher report's URLs (or any of its
  specific factual claims) without running that check and spot-verifying the flagged ones.
  Full workflow: `~/gpt-researcher-local/WORKFLOW.md`.

## Community submission intake (2026-09-25)

The site now has a "Suggest a Resource" button in the header (`SuggestModal` in
index.html, portaled to `document.body` same as `SuggestDropdown`). Since this is a
static GitHub Pages site with no backend, submitting doesn't POST anywhere -- it
builds a prefilled `github.com/.../issues/new?...` URL (title/body/`resource-suggestion`
label) and opens it in a new tab; the visitor finishes the submission on GitHub
itself (needs a free GitHub account).

`tools/import_github_issues.py` is the intake side: pulls open
`resource-suggestion`-labeled issues via `gh issue list`, parses the `**Field:**
value` markdown lines back into the resource-JSON shape, writes
`new_resources_submissions.json` (gitignored scratch file, same convention as every
other `new_resources_*.json`). It deliberately does **not** geocode, merge, or
close issues -- same manual-review discipline as every other source, since an
anonymous submission is a claim, not a verified official source. Full human
workflow is in the script's own docstring: review the output, geocode or mark
`placeless`, run `merge_new_resources.py`, regenerate `community_data.js`, test,
commit, then close the processed issues by hand.

`tools/scheduled_refresh.sh` (also added this session) reruns the 12 cheapest,
purely-API-based fetchers (excludes Italy's Playwright-driven one and Ukraine's
~3.2GB bulk download) + merge + regenerate, on demand or via cron/launchd --
zero LLM tokens per run since it's just HTTP + JSON/CSV parsing, and it never
commits or pushes on its own. The user wired it into their own crontab
(`0 9 1 * * .../tools/scheduled_refresh.sh`, monthly) -- a manual local launchd
install was attempted first but blocked by Claude Code's own auto-mode
persistence guardrail, so cron was used instead.

**Two local-Ollama data-quality tools, added this session:**
- `tools/classify_categories.py` -- for entries whose `type` field isn't one of
  the site's real 6 taxonomy values (checked against `TYPE_META` in `index.html`,
  not invented), asks local qwen2.5-coder:7b to pick the closest real category
  from a closed list (or "uncertain," left unchanged rather than guessed). Pure
  classification, not fact generation, so it's safe to auto-apply -- every
  change is logged to `tools/logs/category_classification_*.log`. Only 40
  entries in the whole dataset actually needed this (legacy "Nonprofit /
  Advocacy"-style values from an older batch import); all 40 were spot-checked
  by hand and applied directly to `community_resources.json`.
- `tools/find_websites_by_address.py` -- for the 67,594 entries with no
  website, builds a **deterministic** search query (`name + city + country`,
  no LLM involved in query generation -- an earlier draft had qwen propose the
  query, but that step added nothing since the template is just as good and
  removes an unnecessary Ollama dependency) and runs it through a real
  DuckDuckGo search (`ddgs` package). Every candidate URL must pass three
  checks -- reachable/not a parking redirect, not a parking page by content
  (matched on strong signals like "domain is for sale," not bare substrings
  like "sedo"/"godaddy" which collide with real site text), and the org's name
  actually present on the page -- before being accepted.
  **Real-world precision on a 100-entry test sample was ~50%, not safe to
  trust or apply.** The 3rd check (name-token-present) cannot distinguish "this
  page is about the org" from "this page IS the org's own site" -- third-party
  directory/aggregator sites (`npino.com`, `medicarelist.com`,
  `ehealthscores.com`, `findabatherapy.org`, `bizapedia.com`,
  `nonprofitlist.org`, `govserv.org`, and similar) legitimately contain the
  org's name (that's their whole purpose) and pass all three checks while not
  being the actual website. This failure was concentrated almost entirely in
  the NPI/small-provider segment of missing-website entries (roughly 60%+
  false-positive rate there); the named-org/registry segment (Autism Society
  state chapters, hospital autism programs, university centers) was much
  cleaner, closer to 80%+ real precision. **Before this could ever be trusted
  for bulk use, it needs a 4th check: a blocklist of known directory/aggregator
  domains** (the ones named above are a good starting list) **or a preference
  for results whose own domain name lexically matches the org name**, neither
  of which exists yet. Stays sample-only / manual-review-only until that's
  built and re-validated -- this is exactly the same "verify before trusting,
  and verify the verifier" discipline the original ~5,000-URL reachability
  audit already established for this project (see commit `357d817`).
  **Round 2 (2026-09-25):** built both fixes -- an `AGGREGATOR_DOMAINS`
  blocklist (rejects a candidate outright, before even fetching it) seeded
  with the 9 confirmed offenders above, plus a same-category preemptive list
  (healthgrades.com, zocdoc.com, manta.com, yelp.com, etc.) -- and a ranking
  heuristic that prefers, among multiple passing candidates, one whose own
  domain contains a normalized fragment of the org's name. Re-ran the same
  100-entry-class sample: 81 verified / 19 review (previously 91/9). Manually
  classified all 81 by URL/domain pattern rather than trusting the script:
  **real precision only rose to ~54-58%, not the fix this needed.** The
  reason: this specific niche (small local ABA-therapy providers) turns out
  to have its own whole ecosystem of directory sites beyond the original 9 --
  `findaba.net`, `findglocal.com`, `findhealthclinics.org`,
  `providerspark.com`, `spectrumheart.com`, `abacarenetwork.com`,
  `abahub.org`, `mentalhealthus.org`, `autismlifeandliving.org`,
  `raisingbrilliance.org`, `opennpi.com`, `opengovus.com`,
  `inclusiveprogramsguide.com`, `volunteersanantonio.org`, `atlantaparent.com`,
  `alabamafamilycentral.org` all showed up as the next-best DDGS result once
  the first 9 were blocked -- a domain blocklist for this vertical is
  whack-a-mole, not a bounded list. (Also added `linkedin.com`/`facebook.com`
  to the blocklist -- social-platform profile pages aren't a "website" field
  in the sense this project wants, even when they're a real, current presence
  for the org.) All 25 newly-observed offenders from this round are now in
  `AGGREGATOR_DOMAINS` for next time, but the script has **not** been
  re-tested against them yet -- the ~54-58% figure is this round's measured
  result, before this round's own blocklist additions.
  The domain-name-match signal is currently only a *tiebreaker* among
  multiple passing candidates -- it did nothing for the majority of entries,
  which only ever produced one passing candidate after the other checks ran.
  **The actual next fix**, not yet built: make domain-name-match a *hard
  requirement* (not just a tiebreaker) at least for the NPI/small-provider
  segment specifically, where the web is directory-saturated -- accept a
  candidate outright if the domain matches the name, otherwise route to
  manual review instead of accepting on token-presence alone. That will cost
  recall (fewer auto-verified) but should raise precision a lot further; try
  it before growing the blocklist more. Note it would have wrongly rejected
  at least one genuine true positive from this round (`bluesprigautism.com`
  for "Trumpet Behavioral Health" -- a real corporate-acquisition rename with
  no lexical overlap), so it needs a manual-review fallback, not an outright
  drop, for domain-mismatch cases.

## Known site-behavior gotchas (already fixed, but good to know the shape of the bug class)

- `shapeAll()` in `index.html` used to silently drop any entry without `coordinates.lat/lng`,
  *and* never propagated the `placeless` field to the app's working dataset — meaning the
  "reach from anywhere" nationwide-orgs list has never actually shown data, ever, including
  the entries that predate this session. Fixed in `70ed78b`: `placeless` entries now skip the
  coordinate requirement and the field is copied through. If you add a new UI feature keyed
  off a data field, double check `shapeAll()`'s field allowlist actually includes it.
- The location geocoder (`geocode()` in index.html) used to hardcode `countrycodes=us`,
  so searching "London" would silently resolve to a US town. Removed in `ccd840e`. If you
  ever need to scope geocoding again, scope it per-feature, not globally — this site now
  covers many countries.
- Any dropdown/overlay rendered inside `.lively-bg` (the landing hero) gets clipped — that
  section has `overflow:hidden` to contain its confetti background. Render such things via
  `ReactDOM.createPortal(..., document.body)` instead of inline, positioned from the real
  anchor element's `getBoundingClientRect()`. See `SuggestDropdown` in index.html for the
  working pattern.

## Standing operational rules (established by the site owner, still apply)

- **Never push to `main` without an explicit, separate "push" instruction** — "commit" alone
  does not imply push.
- **Never commit international/non-US data files without being asked specifically** to
  include them (this has since been done for the batch that's live now, but don't assume
  future harvests should auto-merge).
- Git identity isn't configured in this repo — every commit needs
  `git -c user.name="michaelcraft17" -c user.email="michaelcraft17@gmail.com" commit ...`.
- Test locally before committing: `python3 -m http.server 8765` from the repo root, then
  `http://localhost:8765`. Check port 8765 isn't already in use first (`lsof -i :8765 -t`)
  — it often already is from a prior session.
- After pushing, verify the GitHub Pages build actually finished before declaring done:
  `gh api repos/michaelcraft17/autism-community-resources/pages/builds/latest --jq '.status+" "+(.commit[0:7])'`,
  then spot-check the live file with `curl -sk`.
- `new_resources_*.json` files in the repo root are gitignored scratch/output from the
  fetch tools — present on disk for reference, safe to regenerate or delete, never committed
  directly (their content goes into `community_resources.json` via `merge_new_resources.py`
  instead).

## Current state

- **72,577 total resources** (was 72,537 as of the last handoff). This session's 2026-09-25
  additions: France Asperger-sweep round 2 (+21), Switzerland's new Zefix fetcher (+12, one of
  13 found was already in the dataset), plus 5 incidental adds from `new_resources_uk_cqc.json`/
  `new_resources_canada_national.json`/`new_resources_canada_bc_territories.json` that turned
  out to still have unmerged entries on disk from an earlier session (+1/+1/+5) — found only
  because this session's `merge_new_resources.py` run swept every `new_resources_*.json` file
  in the repo root, not something newly fetched this session. Net this session: **+40**.
  See the France/Netherlands/Switzerland fetcher entries and the "Poland, Portugal, Austria"
  ruled-out entry above for what was actually attempted and found this round.
- 72,537 total resources (was 48,664 at the start of this thread of work; 69,841 two handoffs
  ago; 72,375 as of commit `2d9dffc`). The 2026-09-23/24 European push (Autism-Europe full
  directory + France RNA + Netherlands ANBI + Belgium KBO + Italy RUNTS) added ~2,530 — France's
  RNA registry was the single biggest addition this project has made from any one source. A
  follow-up pass added Norway (Bronnoysund register, 32 net-new after deduping one national-org
  collision against the existing Autism-Europe entry) and Finland (YTJ register, 2 net-new).
  A third pass (2026-09-24, "build out the single-listing countries," now five research rounds
  plus a sixth to actually implement the last one) targeted the 19 countries that had exactly
  one resource — round 1 added Czech Republic (+7), Estonia (+8), Latvia (+7), Slovenia (+1),
  Denmark (+1), Germany (+1); round 2 added Cyprus (+4) and Ukraine (+41) via its full national
  legal-entity register; round 3 added Greece (+3) and, the second-deepest addition of this
  whole pass, **Slovakia (+33)** via its current unified legal-entity registry (RPO); rounds 4
  and 5 found no new data but ruled out the remaining 6 with much more specific evidence each
  (see "Ruled out"); a final round added **Bulgaria (+13, after a follow-up pass found 4 more)** via a third-party API
  (`bulgaria_companybook_fetch.py`) that republishes Bulgaria's own official CC-BY open data —
  the one source in this whole pass that needed a free account sign-up, done with the site
  owner's explicit go-ahead.
  A follow-up "Asperger sweep" (2026-09-24) went back through every already-built fetcher and
  added "asperger" (Asperger's, now considered part of the autism spectrum) as an extra search
  term, since the original autism-root terms never covered it. Real yield across 10 countries
  tested: Estonia +4 (including a second national organization the original terms missed
  entirely, via a different grammatical form of "autist," not "asperger" itself), Norway +3,
  Finland +1, Slovakia +1, Bulgaria +4 (already counted above) — **13 net-new entries**, plus
  two real code bugs fixed along the way (Finland/Norway both track name-change history
  separately from an entity's current name, and weren't being searched). Czech Republic,
  Latvia, Slovenia, Ukraine, Cyprus tested and confirmed zero real matches. Worth re-running
  this same sweep for Greece (a live retest kept timing out, unrelated to this project) and
  worth trying on any future non-English-speaking country's fetcher as a standard extra term,
  not just a one-off for Bulgaria.
  Only 5 of the original 19 (Lithuania, Andorra, Croatia,
  Luxembourg, Romania) remain effectively single-entry — see "Ruled out" below for what was
  tried and why each didn't pan out. Three rounds in this pass each turned up a real, working
  source for a country previously marked as a dead end (Ukraine, Slovakia, Bulgaria) —
  worth re-checking a "ruled out" entry for a genuinely different domain/system, or a
  legitimately-sourced third party, before accepting it as final.
  One dedup gap found and fixed by hand *twice* now: `merge_new_resources.py`'s name-
  normalization strips all non-alphanumeric characters, so "Autismeforeningen I Norge" and
  "Autismeforeningen I Norge (A.I.N.)" don't collapse to the same key (the parenthetical
  acronym gets concatenated onto the name with no separator). Fixed once by removing the
  duplicate from `community_resources.json` directly, then re-introduced a session later
  because the stale `new_resources_norway.json` scratch file on disk still had it and got
  re-merged — **removed that scratch file for good this time**, and as a general rule, any
  entry manually excluded from `community_resources.json` should also be deleted from its
  source `new_resources_*.json` file (or the file deleted outright once merged), not just
  removed from the merged output.
- `tools/belgium_kbo_fetch.py` and `tools/italy_runts_fetch.py` joined this session. Belgium's
  KBO has a PDF-export endpoint that works with plain `requests` once the right (undocumented)
  param set is used — found by driving the HTML form once with Playwright to capture it, then
  confirmed to work via plain curl afterward, no Playwright needed at request time. Italy's
  RUNTS has no API or export at all — a legacy ASP.NET WebForms/UpdatePanel portal, driven live
  with Playwright, and its AJAX pagination turned out to be genuinely flaky (intermittent full
  page reloads mid-scrape). That entry is a documented partial capture (89 of ~244 raw matches
  across 3 search terms) — see the script's docstring before assuming it's exhaustive.
  Spain's equivalent registry search page returned an HTTP 403 (real WAF, not attempted
  further) and Germany's Vereinsregister has no free bulk/open dataset — both are dead ends
  for now, not just untried.
- Location search has Google-Maps-style autocomplete (debounced Nominatim, portal-rendered
  dropdown, keyboard + mouse nav) on both the landing page and header search bars.
- `tools/preview/` (gitignored) is a standalone local debug map — loads whatever's in
  `tools/wikidata_scratch/_added_preview.json` or similar and plots it with Leaflet, useful
  for eyeballing a batch of newly-merged pins before trusting them. Not wired to anything
  automatically; regenerate its data file by hand when needed (diff current vs. a prior git
  commit's `community_resources.json` by normalized name, same approach used this session).

## Natural next steps (not started, no commitment implied)

- More EU national association/charity registries, same pattern as `france_rna_fetch.py`/
  `netherlands_anbi_fetch.py`/`belgium_kbo_fetch.py`/`italy_runts_fetch.py`/
  `norway_brreg_fetch.py`/`finland_ytj_fetch.py`/`switzerland_zefix_fetch.py`. Tried so far,
  best to worst yield: France (real search API, 2,404 hits after the 2026-09-25 Asperger-sweep
  expansion), Italy (no API, Playwright-driven, 89 captured but pagination was flaky — worth a
  clean re-run, needs Playwright installed), Norway (real search API, 36 hits incl. regional
  chapters), Belgium (PDF export works via plain curl once you have the right params, 34 hits —
  the working param set wasn't preserved in the script and needs re-capturing via Playwright),
  Switzerland (undocumented but unauthenticated JSON endpoint on the public site, 13 hits),
  Netherlands (bulk XML, name-only filtering, 21 hits), Finland (real search API, only 3 hits —
  small country, no separate regional-chapter registrations). Ruled out: Spain's Ministry of
  Interior search page (`interior.gob.es`) returned a real HTTP 403 (WAF) — not pursued further
  per the no-evasion policy; Germany's Vereinsregister has no free bulk/open dataset, only
  per-court paid extracts; **Poland** (KRS's free API is lookup-by-known-number only, consumer
  search portal is behind Incapsula/403, no bulk dane.gov.pl dataset), **Austria** (ZVR's own
  documentation states bulk/scripted queries aren't permitted, a stated policy restriction —
  ruled out on principle, not attempted) — see the "Ruled out" entry above for the full
  evidence on both, added 2026-09-25. Checked this round but not pursued: Denmark's official
  CVR data is only distributed via a complex Elasticsearch-based bulk service requiring
  registration (`distribution.virk.dk`) — a free unofficial wrapper (`cvrapi.dk`) works for
  one-off lookups but is rate-limited and not an official source, so building against it wasn't
  a clean win. **Portugal**'s RNPC name-check tool is reachable but needs a live Playwright
  session to drive (ASP.NET WebForms postback, no JSON API) — same blocker as Belgium/Italy,
  worth revisiting once Playwright is available in this environment. Not yet tried: Czech
  Republic (as a *deeper* pass — it's already in the dataset via ARES), other
  Central/Eastern Europe.
- Scotland/Wales/Northern Ireland care registries, same pattern as `cqc_uk_fetch.py`.
- Wider Wikidata org-class coverage, or non-English "autis-root" search terms for
  non-Latin-script countries (Japan, China, Korea, Arabic-speaking countries) — explicitly
  deferred this session in favor of the simpler English-root search.
- Tiled/per-region OpenStreetMap Overpass harvesting, if someone wants to invest the time to
  make it politeness-compliant with the public instance's rate limits.
- Germany/France/Japan/South Africa GPT-Researcher reports exist in
  `~/gpt-researcher-local/reports/` but were low-yield on verification and discarded —
  a from-scratch structured-dataset approach (a national registry, if one exists and is
  findable) would likely beat re-running the LLM narration approach on these.
