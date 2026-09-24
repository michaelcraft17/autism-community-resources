# Accessibility Mapper — Autism & Special Needs Community Resources

A free, interactive directory of autism and special needs resources — over 72,000 of them,
across 30+ countries.

## Live site

**[autismcommunityorg.org](https://autismcommunityorg.org/)**

## Why this is different from Google Maps or Apple Maps

Anyone can add or edit a listing on Google Maps or Apple Maps. Nobody can here. Every resource
in this directory comes from a source we can point to: a government registry, a national
health or disability database, an official membership directory, or an organization's own
published records. If we can't verify where a listing came from, it doesn't go in.

That means:
- No fake or spammed listings
- No businesses that closed years ago still showing as open
- Every entry has a real, checkable source behind it

## What's in it

- **72,000+ resources**: advocacy groups, therapy providers, schools, medical clinics, and
  support organizations
- **30+ countries**: built out from the US and UK to cover most of Europe, plus Canada,
  Australia, New Zealand, and Ireland
- **An interactive map**: search any city, ZIP code, or address and see what's nearby, sorted
  by distance
- **Accessibility built in**: dark mode, keyboard navigation, screen reader support, a reading
  guide, and adjustable contrast/motion settings

## Where the data comes from

Resources are pulled from official, structured sources — never scraped indiscriminately and
never written by an AI guessing at what might exist. Sources used so far include:

- Government registries: the UK's Care Quality Commission directory, France's national
  association registry (RNA), Belgium's business register (KBO/BCE), Italy's national
  third-sector register (RUNTS), the Netherlands' ANBI tax-status register, and the US NPI
  Registry
- Wikidata, for internationally notable autism and disability organizations
- Official membership directories, like Autism-Europe's own list of national member
  associations
- State and regional resource lists compiled by hand and checked against each organization's
  own site

Every source is documented in the data-collection scripts in [`tools/`](tools/), so anyone can
see exactly where a batch of listings came from.

## How to use it

1. Enter your city, ZIP code, or address — or click "Use my current location"
2. Browse resources sorted by distance, or search by keyword
3. Filter by type: advocacy, therapy, education, medical, or social support
4. Save favorites, get directions, or call directly from a listing
5. Turn on dark mode or adjust accessibility settings from the menu — your preferences are
   saved on your device

## Built with

Plain HTML, CSS, and JavaScript (React via in-browser Babel — no build step), Leaflet for the
map, and OpenStreetMap for tiles and geocoding. The data pipeline is a set of Python scripts
in `tools/` that pull from official APIs and open datasets, documented individually.

## Contributing

Know of a resource that should be listed, or an official data source we haven't used yet?
Open an issue with the details — including where the information comes from. We don't accept
direct edits to the resource database itself, since every listing needs to trace back to a
verifiable source.

Code contributions (bug fixes, accessibility improvements, new features) are welcome — fork
the repo and open a pull request.

## Disclaimer

Information can change. Always confirm details directly with a provider before relying on
them, especially for anything time-sensitive like intake availability or insurance
acceptance.

## Emergency resources

- **Autism Society**: 1-800-328-8476
- **Crisis Text Line**: Text HOME to 741741
- **National Suicide Prevention Lifeline**: 988

## License

The source code (site, scripts, tooling) is open source under the [MIT License](LICENSE).

The compiled resource database (`community_data.js` / `community_resources.json`) is **not**
covered by that license. Automated scraping, bulk downloading, and redistribution of the
database are restricted — see [TERMS.md](TERMS.md).

---

Built by a Cal Poly Pomona Computer Science student, one verified source at a time.
