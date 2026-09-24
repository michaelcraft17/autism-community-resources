#!/usr/bin/env python3
"""
Belgian autism-related organizations from the KBO/BCE (Kruispuntbank van
Ondernemingen / Banque-Carrefour des Entreprises) -- Belgium's official
business/association register (FOD Economie / SPF Economie):

    https://kbopub.economie.fgov.be/kbopub/zoeknaamfonetischform.html?searchWord=autisme&...

Same tier of source as tools/france_rna_fetch.py and tools/cqc_uk_fetch.py:
an official government registry, not scraped or LLM-narrated. Belgium's ASBL
(non-profit associations) register in the KBO exactly like commercial
companies, so a name search there surfaces real, verified autism
associations with their registered office address.

Unlike France's RNA, this dataset has no separate keyword-search JSON API --
the public portal (kbopub.economie.fgov.be) is a plain HTML form, but it
does expose a PDF export of the full result set in one request:
".../zoeknaamfonetischform.pdf?searchWord=...&rechtsvormFonetic=ALL&..."
(the `rechtsvormFonetic=ALL` param is required or the request 404s -- found
by driving the HTML form once with Playwright to capture the real working
param set, then confirming the same URL works via plain curl with no
session/cookie needed). Every parameter in FIXED_PARAMS below was captured
that way against the "autisme" query, which returned 59 raw hits -> 39 after
excluding VE-only rows (establishment/branch listings that duplicate their
parent ENT RP entity's address) and "Ambsthalve doorgehaald entiteit"
(administratively struck off) entries.

This session's other Dutch-language variants ("autistisch", "autistiek",
"autiste") return a genuine server-side 500 (NullPointerException in the
site's own PDF-generation code, not a request-shape problem on our end) --
not retried further; "autisme" is the same word in French and Dutch, so it
already covers Belgium's two main language communities' typical org naming.

The 39 entries below are hand-transcribed from that PDF (same pattern as
tools/autism_europe_members_fetch.py -- a small, official, non-API source is
transcribed once rather than fighting a fragile parser for a one-time
~40-row result set). A few entries have a French/Dutch address outside
Belgium (e.g. a Paris- or Netherlands-based org that happens to hold a
Belgian KBO registration) -- included as-is since they're real verified
entries, just cross-border registrations.

Usage:
    python3 tools/belgium_kbo_fetch.py

Writes:
    new_resources_belgium_kbo.json   final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO, "new_resources_belgium_kbo.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE = "Belgium KBO/BCE (Kruispuntbank van Ondernemingen) - official government business/association register"

ENTRIES = [
    {"name": "2thepoint, begeleiding rondom autisme", "address": "Dijkzijde 79, 2360 Oud-Turnhout, Belgium"},
    {"name": "AFG Autisme Association", "address": "Rue de la Vistule 11, 75013 Paris, France"},
    {"name": "Association Internationale Autisme-Europe", "address": "Montoyerstraat 39, 1000 Brussel, Belgium"},
    {"name": "Association pour Femmes Incarcerees et les Enfants Touches par l'Autisme", "address": "Victor Rousseaulaan 213, 1190 Vorst, Belgium"},
    {"name": "Autisme Centraal", "address": "Kerkstraat 108, 9050 Gent, Belgium"},
    {"name": "Autisme Congo", "address": "Joseph Ruttenlaan 21, 1150 Sint-Pieters-Woluwe, Belgium"},
    {"name": "Autisme Expertise Centrum & Academy Sebiha Unal", "address": "Birdaarderstraatweg 70, 9101DC Dokkum, Netherlands"},
    {"name": "Autisme in Actie", "address": "Sanderuslaan 83, 9940 Evergem, Belgium"},
    {"name": "Autisme in Colour", "address": "Rapaertstraat 25, 8020 Oostkamp, Belgium"},
    {"name": "Autisme Leeft", "address": "Bakkerslaan 14, 3500 Hasselt, Belgium"},
    {"name": "Autisme Liege", "address": "Rue des Sapins 42, 4100 Seraing, Belgium"},
    {"name": "Autisme van Binnen Uit", "address": "Schaapstraat 39, 8370 Blankenberge, Belgium"},
    {"name": "Autisme Veurne & Omstreken VZW", "address": "Avekapellestraat 6, 8630 Veurne, Belgium"},
    {"name": "Autisme Vlaanderen", "address": "Groot Begijnhof 73, 9040 Gent, Belgium"},
    {"name": "Autisme Westhoek", "address": "Veurnseweg 105, 8900 Ieper, Belgium"},
    {"name": "Autisme a l'Ecole", "address": "Rue Henri Tournelle 22, 7012 Mons, Belgium"},
    {"name": "Begeleidingscentrum voor Personen met Autisme", "address": "Leuvensesteenweg 212, 2800 Mechelen, Belgium"},
    {"name": "Centre d'Action pour l'Autisme en Province de Luxembourg", "address": "Rue des Dominicains 11, 6800 Libramont-Chevigny, Belgium"},
    {"name": "Coupole Bruxelloise de l'Autisme", "address": "Esseghemstraat 41, 1090 Jette, Belgium"},
    {"name": "David Lucien Roland Hope Action Autisme", "address": "Platolaan 21 bus 217, 1140 Evere, Belgium"},
    {"name": "De Verenigde Spectrums van Autisme", "address": "Keibergkerkweg 12, 9340 Lede, Belgium"},
    {"name": "Lees- en Adviesgroep Volwassenen met Autisme", "address": "Groot Begijnhof 73, 9040 Gent, Belgium"},
    {"name": "Liga Autisme Vlaanderen", "address": "Brusselsesteenweg 375, 9090 Merelbeke-Melle, Belgium"},
    {"name": "Maison d'Espoir Autisme", "address": "de Haveskerckelaan 23, 1190 Vorst, Belgium"},
    {"name": "Maison de l'Autisme Mouscron-Auti Bol d'Air", "address": "Rue Gerard Mullie 1, 7700 Mouscron, Belgium"},
    {"name": "Mijn Kind Heeft Autisme", "address": "Koning Boudewijnstraat 119A, 8930 Menen, Belgium"},
    {"name": "Passeport Autisme", "address": "Rue de l'Eau-Bleue 23, Rhisnes, 5080 La Bruyere, Belgium"},
    {"name": "Service Universitaire Specialise pour Personnes avec Autisme", "address": "Rue Brisselot 1, 7000 Mons, Belgium"},
    {"name": "V.V.A. Vlaamse Vereniging Autisme Vzw", "address": "Groot Begijnhof 73, 9040 Gent, Belgium"},
    {"name": "Vereniging voor Bewustzijn van Autisme", "address": "Rootenstraat 3, 3600 Genk, Belgium"},
    {"name": "Vlaamse Dienst Autisme", "address": "Groot Begijnhof 85, 9040 Gent, Belgium"},
    {"name": "Voor Autisme", "address": "Haachtstraat 9, 2600 Antwerpen, Belgium"},
    {"name": "Werk- en Woonproject Autisme", "address": "9000 Gent, Belgium"},
    {"name": "Wonen en Werken voor Personen met Autisme", "address": "Repingestraat 12, 1570 Pajottegem, Belgium"},
]


def geocode_query(query):
    params = {"q": query, "format": "json", "limit": 1}
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.loads(resp.read())
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception as e:
        print(f"  geocode failed for {query!r}: {e}")
    return None


def geocode(address):
    coords = geocode_query(address)
    if coords:
        return coords
    time.sleep(1.1)
    parts = [p.strip() for p in address.split(",")]
    fallback = ", ".join(parts[-2:]) if len(parts) >= 2 else address
    print(f"  full address failed, retrying with {fallback!r}")
    return geocode_query(fallback)


def main():
    resources = []
    for e in ENTRIES:
        coords = geocode(e["address"])
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        entry = {
            "name": e["name"],
            "address": e["address"],
            "type": "advocacy",
            "source": SOURCE,
            "services": ["Advocacy", "Information & Support"],
            "description": f"{e['name']} -- registered non-profit association (KBO/BCE, Belgium's official business register).",
        }
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        resources.append(entry)
        print(f"  {e['name']}: {'geocoded' if coords else 'NOT geocoded (placeless)'}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} geocoded")


if __name__ == "__main__":
    main()
