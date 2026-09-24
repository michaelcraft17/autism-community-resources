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
  retries with progressively fewer trailing comma-segments until one resolves.
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
  owner died ("... Inngår I Dødsbo" — estate in probate).
- `finland_ytj_fetch.py` — Finland's PRH Business Information System (YTJ), same tier of
  official registry. Much smaller country, much smaller yield (2 net-new active orgs: the
  Autism Foundation and the national Autism Spectrum Association) — Finland doesn't appear to
  register regional chapters as separate legal entities the way Norway does.
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
  Added 9 organizations, all active. Two real address-geocoding gotchas fixed here, worth
  knowing about for any future Bulgarian source: (1) the registry's precise street-level
  address routinely fails to resolve in Nominatim as one string (same class of issue as
  Estonia's hierarchical addresses) -- falls back to city-level; (2) the API's own
  `settlement` field carries a "гр."/"с." (town/village) type-prefix that *also* breaks
  Nominatim even at the fallback step (e.g. "гр. Панагюрище" resolves to nothing, but plain
  "Панагюрище" resolves fine) -- stripped explicitly.
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
  after Ukraine.
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

- 72,523 total resources (was 48,664 at the start of this thread of work; 69,841 two handoffs
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
  (see "Ruled out"); a final round added **Bulgaria (+9)** via a third-party API
  (`bulgaria_companybook_fetch.py`) that republishes Bulgaria's own official CC-BY open data —
  the one source in this whole pass that needed a free account sign-up, done with the site
  owner's explicit go-ahead. Only 5 of the original 19 (Lithuania, Andorra, Croatia,
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
  `norway_brreg_fetch.py`/`finland_ytj_fetch.py`. Tried so far, best to worst yield: France
  (real search API, 2,383 hits), Italy (no API, Playwright-driven, 89 captured but pagination
  was flaky — worth a clean re-run), Norway (real search API, 32 hits incl. regional chapters),
  Belgium (PDF export works via plain curl once you have the right params, 34 hits), Netherlands
  (bulk XML, name-only filtering, 21 hits), Finland (real search API, only 2 hits — small
  country, no separate regional-chapter registrations). Ruled out: Spain's Ministry of Interior
  search page (`interior.gob.es`) returned a real HTTP 403 (WAF) — not pursued further per the
  no-evasion policy; Germany's Vereinsregister has no free bulk/open dataset, only per-court
  paid extracts. Checked this round but not pursued: Denmark's official CVR data is only
  distributed via a complex Elasticsearch-based bulk service requiring registration
  (`distribution.virk.dk`) — a free unofficial wrapper (`cvrapi.dk`) works for one-off lookups
  but is rate-limited and not an official source, so building against it wasn't a clean win;
  Switzerland's Zefix company registry API requires authentication (401 without credentials) —
  untried further; Poland's KRS/dane.gov.pl and Portugal's RNPC didn't yield an obvious
  name-search API on a quick check — worth real investigation, not a dead end. Not yet tried:
  Czech Republic, Austria, other Central/Eastern Europe.
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
