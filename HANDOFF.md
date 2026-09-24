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
- `merge_new_resources.py` — generic merge step: dedupes any `new_resources_*.json` file in
  the repo root against `community_resources.json` (by normalized name and website domain)
  and appends the rest. Run this after any of the fetchers above, then regenerate
  `community_data.js`.

**Ruled out, don't re-attempt without a new angle:**
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

- 72,409 total resources (was 48,664 at the start of this thread of work; 69,841 two handoffs
  ago; 72,375 as of commit `2d9dffc`). The 2026-09-23/24 European push (Autism-Europe full
  directory + France RNA + Netherlands ANBI + Belgium KBO + Italy RUNTS) added ~2,530 — France's
  RNA registry was the single biggest addition this project has made from any one source. A
  follow-up pass added Norway (Bronnoysund register, 32 net-new after deduping one national-org
  collision against the existing Autism-Europe entry) and Finland (YTJ register, 2 net-new).
  One dedup gap found and fixed by hand: `merge_new_resources.py`'s name-normalization strips
  all non-alphanumeric characters, so "Autismeforeningen I Norge" and "Autismeforeningen I
  Norge (A.I.N.)" don't collapse to the same key (the parenthetical acronym gets concatenated
  onto the name with no separator) — worth knowing about if a future merge silently produces a
  near-duplicate pin for the same org under a slightly different name suffix.
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
